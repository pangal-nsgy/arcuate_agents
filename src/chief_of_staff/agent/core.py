"""Core agent loop — Claude-powered reasoning with tool use, config-driven, activity-tracked."""

from __future__ import annotations

import asyncio
import functools
import logging
import time
from typing import Any

import anthropic

from chief_of_staff.config import settings
from chief_of_staff.agent.activity import (
    ActivityTimer, log_activity, TOOL_USE, DELEGATION, ERROR,
)
from chief_of_staff.agent.registry import AgentConfig, get_registry
from chief_of_staff.agent.tools import get_tool_definitions, get_server_tools, execute_tool
from chief_of_staff.agent.retry import retry_async

logger = logging.getLogger(__name__)

# Tools that need extended timeouts (run subprocesses, network calls, etc.)
_LONG_TIMEOUT_TOOLS = {"run_python", "install_package", "execute_task_plan", "fetch_webpage"}
_LONG_TIMEOUT = 120
_DEFAULT_TOOL_TIMEOUT = 30


class Agent:
    """A configurable agent that loads behavior from YAML config."""

    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self.client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key,
            timeout=60.0,
        )

    def reload_config(self) -> None:
        """Re-read config from disk (picks up self-modifications)."""
        registry = get_registry()
        fresh = registry.get(self.config.name)
        if fresh:
            self.config = fresh

    async def respond(
        self,
        user_message: str,
        conversation_history: list[dict[str, Any]] | None = None,
        channel: str = "",
        user_id: str = "",
        session_id: str = "",
    ) -> str:
        """Process a message and return the agent's response.

        Wraps _respond_inner with an overall request timeout.
        """
        timeout = self.config.request_timeout
        try:
            return await asyncio.wait_for(
                self._respond_inner(user_message, conversation_history, channel, user_id, session_id),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            log_activity(
                agent_name=self.config.name,
                action_type=ERROR,
                action_detail=f"Request timed out after {timeout}s",
                channel=channel,
                user_id=user_id,
                session_id=session_id,
            )
            return "I took too long on that one. Try breaking the request into smaller parts."

    async def _respond_inner(
        self,
        user_message: str,
        conversation_history: list[dict[str, Any]] | None = None,
        channel: str = "",
        user_id: str = "",
        session_id: str = "",
    ) -> str:
        """Core agent loop — handles multi-turn tool use, logs all activity."""
        self.reload_config()

        messages = list(conversation_history or [])

        # Build system prompt from config (includes standing instructions + memory)
        system_prompt = self.config.build_system_prompt()

        # Retrieve relevant context from knowledge base (sync ChromaDB — run in thread)
        try:
            from chief_of_staff.knowledge.store import get_context_for_query
            loop = asyncio.get_event_loop()
            context = await loop.run_in_executor(
                None, functools.partial(get_context_for_query, user_message)
            )
            if context:
                system_prompt += f"\n\n--- RELEVANT CONTEXT FROM KNOWLEDGE BASE ---\n{context}\n--- END CONTEXT ---"
        except Exception as e:
            logger.warning(f"Knowledge base unavailable, continuing without context: {e}")

        if user_id:
            system_prompt += f"\n\nUser identifier: {user_id}"

        messages.append({"role": "user", "content": user_message})

        # Get tool definitions for this agent's allowed tools
        tool_defs = get_tool_definitions(self.config.get_resolved_tools())
        server_tools = get_server_tools(self.config.server_tools)

        # Agentic loop
        start_time = time.time()
        for iteration in range(self.config.max_iterations):
            try:
                response = await retry_async(
                    self.client.messages.create,
                    model=self.config.model,
                    max_tokens=self.config.max_tokens,
                    system=system_prompt,
                    tools=server_tools + tool_defs,
                    messages=messages,
                )
            except Exception as e:
                log_activity(
                    agent_name=self.config.name,
                    action_type=ERROR,
                    action_detail=f"API call failed: {e}",
                    channel=channel,
                    user_id=user_id,
                    session_id=session_id,
                )
                raise

            assistant_content = response.content
            messages.append({"role": "assistant", "content": assistant_content})

            # Find custom tool calls (server tools handled by Anthropic)
            tool_calls = [b for b in assistant_content if b.type == "tool_use"]

            if not tool_calls:
                # Final text response
                text_blocks = [b.text for b in assistant_content if hasattr(b, "text")]
                return "\n".join(text_blocks) if text_blocks else "Processed — nothing to add."

            # Execute custom tool calls
            tool_results = []
            for tool_call in tool_calls:
                tool_start = time.time()
                logger.info(f"[{self.config.name}] Tool: {tool_call.name}({tool_call.input})")

                # Per-tool timeout (extended for long-running tools)
                tool_timeout = _LONG_TIMEOUT if tool_call.name in _LONG_TIMEOUT_TOOLS else _DEFAULT_TOOL_TIMEOUT
                try:
                    result = await asyncio.wait_for(
                        execute_tool(
                            tool_call.name,
                            tool_call.input,
                            agent_name=self.config.name,
                        ),
                        timeout=tool_timeout,
                    )
                except asyncio.TimeoutError:
                    result = f"Tool '{tool_call.name}' timed out after {tool_timeout}s."
                    logger.warning(result)

                tool_duration = int((time.time() - tool_start) * 1000)

                log_activity(
                    agent_name=self.config.name,
                    action_type=TOOL_USE,
                    action_detail=tool_call.name,
                    input_summary=str(tool_call.input)[:500],
                    output_summary=result[:500],
                    channel=channel,
                    user_id=user_id,
                    session_id=session_id,
                    duration_ms=tool_duration,
                )

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_call.id,
                    "content": result,
                })

            messages.append({"role": "user", "content": tool_results})

        return "Hit reasoning limit. Try breaking down the request."


class ChiefOfStaff(Agent):
    """Chief of Staff agent — loads from the chief_of_staff.yaml config."""

    def __init__(self) -> None:
        registry = get_registry()
        config = registry.get("chief_of_staff")
        if not config:
            # Fallback: create a minimal config
            logger.warning("chief_of_staff.yaml not found, using fallback config")
            config = AgentConfig(
                name="chief_of_staff",
                display_name="Arcuate Chief of Staff",
                system_prompt="You are the Chief of Staff at Arcuate Health.",
                tools=["search_knowledge"],
            )
        super().__init__(config)


# Unified agent cache
_agents: dict[str, Agent] = {}


def get_agent() -> ChiefOfStaff:
    """Get the singleton Chief of Staff agent."""
    if "chief_of_staff" not in _agents:
        _agents["chief_of_staff"] = ChiefOfStaff()
    agent = _agents["chief_of_staff"]
    assert isinstance(agent, ChiefOfStaff)
    return agent


def get_agent_by_name(name: str) -> Agent | None:
    """Get a cached agent by name. Creates it if the config exists."""
    if name in _agents:
        return _agents[name]
    registry = get_registry()
    config = registry.get(name)
    if config:
        agent = Agent(config)
        _agents[name] = agent
        return agent
    return None


# Backward-compatible alias
get_sub_agent = get_agent_by_name
