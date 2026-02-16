"""Core agent loop — Claude-powered reasoning with tool use, config-driven, activity-tracked.

3-layer architecture:
  1. Tool Planner (Haiku) — selects 5-12 relevant tools from the full set
  2. Executor (Opus) — runs the agentic loop with focused tool set
  3. Overflow (GPT-4.1) — continues if Anthropic exhausts max_iterations
"""

from __future__ import annotations

import asyncio
import functools
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any

import anthropic

from chief_of_staff.config import settings
from chief_of_staff.agent.activity import (
    ActivityTimer, log_activity, TOOL_USE, DELEGATION, ERROR,
    TOOL_PLANNING, OVERFLOW_RESPONSE,
)
from chief_of_staff.agent.registry import AgentConfig, get_registry
from chief_of_staff.agent.tools import get_tool_definitions, get_server_tools, execute_tool
from chief_of_staff.agent.retry import retry_async
from chief_of_staff.agent.lanes import run_main_lane
from chief_of_staff.agent.request_context import (
    set_request_context, reset_request_context, emit_progress,
)

logger = logging.getLogger(__name__)

# Tools that need extended timeouts (run subprocesses, network calls, etc.)
_LONG_TIMEOUT_TOOLS = {"run_python", "install_package", "execute_task_plan", "fetch_webpage"}
_LONG_TIMEOUT = 120
_DEFAULT_TOOL_TIMEOUT = 30

# Meta-tools that should always be available regardless of planner output
_ALWAYS_AVAILABLE_TOOLS = {
    "report_progress", "remember", "recall_memory",
    "delegate_task", "spawn_sub_agent_task",
    "create_task_plan", "execute_task_plan", "scaffold_skill",
    "list_available_tools",
}

_CAPABILITY_REFUSAL_PATTERNS = (
    r"\bi don't have\b",
    r"\bi do not have\b",
    r"\bi can't\b",
    r"\bi cannot\b",
    r"\bnot available\b",
    r"\bno tool\b",
    r"\bmissing capability\b",
)


# Human-friendly names for progress messages
_TOOL_DISPLAY_NAMES = {
    "search_knowledge": "Searching knowledge base",
    "list_recent_emails": "Checking recent emails",
    "search_meetings": "Searching meetings",
    "send_email": "Sending email",
    "send_sms": "Sending SMS",
    "draft_document": "Drafting document",
    "send_meeting_bot": "Sending meeting bot",
    "delegate_task": "Delegating to specialist",
    "spawn_sub_agent_task": "Spawning sub-agent task",
    "create_sub_agent": "Creating sub-agent",
    "run_python": "Running code",
    "fetch_webpage": "Fetching webpage",
    "install_package": "Installing package",
    "remember": "Saving to memory",
    "recall_memory": "Recalling memory",
    "update_own_instructions": "Updating instructions",
    "read_own_code": "Reading source code",
    "edit_own_code": "Editing source code",
    "deploy_changes": "Deploying changes",
    "create_task_plan": "Creating task plan",
    "execute_task_plan": "Executing task plan",
    "scaffold_skill": "Scaffolding new skill",
    "list_available_tools": "Checking available tools",
}


def _looks_like_capability_refusal(text: str) -> bool:
    """Heuristic to detect refusal due to missing capabilities/tools."""
    lower = (text or "").lower()
    if not lower.strip():
        return False
    if "tool" not in lower and "capab" not in lower:
        return False
    return any(re.search(pattern, lower) for pattern in _CAPABILITY_REFUSAL_PATTERNS)


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

    async def _plan_tools(
        self,
        user_message: str,
        all_tool_names: list[str],
        tool_defs: list[dict[str, Any]],
    ) -> list[str]:
        """Use Haiku to select which tools are relevant for this request.

        Returns a filtered list of tool names. Falls back to all tools on error.
        """
        if len(all_tool_names) <= 10:
            # Not enough tools to benefit from planning
            return all_tool_names

        # Build compact tool summary (name + first line of description)
        tool_lines = []
        for td in tool_defs:
            name = td.get("name", "")
            desc = td.get("description", "").split("\n")[0][:100]
            tool_lines.append(f"- {name}: {desc}")
        tool_list_str = "\n".join(tool_lines)

        planner_prompt = (
            f"Given this user request, select which tools are needed. "
            f"Return ONLY a JSON array of tool names (5-12 tools).\n\n"
            f'Request: "{user_message}"\n\n'
            f"Available tools:\n{tool_list_str}\n\n"
            f"Selected tools (JSON array):"
        )

        try:
            planner_start = time.time()
            response = await self.client.messages.create(
                model=self.config.planner_model,
                max_tokens=512,
                messages=[{"role": "user", "content": planner_prompt}],
            )
            planner_duration = int((time.time() - planner_start) * 1000)

            # Parse the JSON response
            text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    text += block.text

            # Extract JSON array from response (handle markdown code blocks)
            text = text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

            selected = json.loads(text)
            if not isinstance(selected, list) or not selected:
                logger.warning("Tool planner returned invalid format, using all tools")
                return all_tool_names

            # Validate tool names exist
            valid_tools = [t for t in selected if t in set(all_tool_names)]
            if not valid_tools:
                logger.warning("Tool planner returned no valid tools, using all tools")
                return all_tool_names

            # Merge in always-available tools
            for meta_tool in _ALWAYS_AVAILABLE_TOOLS:
                if meta_tool in set(all_tool_names) and meta_tool not in set(valid_tools):
                    valid_tools.append(meta_tool)

            log_activity(
                agent_name=self.config.name,
                action_type=TOOL_PLANNING,
                action_detail=f"Selected {len(valid_tools)}/{len(all_tool_names)} tools",
                input_summary=user_message[:500],
                output_summary=json.dumps(valid_tools)[:500],
                duration_ms=planner_duration,
            )

            logger.info(
                f"[{self.config.name}] Tool planner: {len(valid_tools)}/{len(all_tool_names)} tools "
                f"in {planner_duration}ms — {valid_tools}"
            )
            return valid_tools

        except Exception as e:
            logger.warning(f"Tool planner failed ({e}), using all tools")
            return all_tool_names

    async def respond(
        self,
        user_message: str,
        conversation_history: list[dict[str, Any]] | None = None,
        channel: str = "",
        user_id: str = "",
        session_id: str = "",
        progress_callback: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        """Process a message and return the agent's response.

        Wraps _respond_inner with an overall request timeout.
        """
        timeout = self.config.request_timeout
        try:
            result = await asyncio.wait_for(
                run_main_lane(
                    self._respond_inner(
                        user_message, conversation_history,
                        channel, user_id, session_id, progress_callback,
                    )
                ),
                timeout=timeout,
            )
            return result
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
        progress_callback: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        """Core agent loop — handles multi-turn tool use, logs all activity."""
        # Set request context HERE (inside the Task) so ContextVar is definitely
        # available to all tool calls, emit_progress, etc.
        token = set_request_context(
            channel=channel, user_id=user_id, session_id=session_id,
            progress_callback=progress_callback,
        )
        try:
            return await self._respond_loop(
                user_message, conversation_history, channel, user_id, session_id,
            )
        finally:
            reset_request_context(token)

    async def _respond_loop(
        self,
        user_message: str,
        conversation_history: list[dict[str, Any]] | None = None,
        channel: str = "",
        user_id: str = "",
        session_id: str = "",
    ) -> str:
        """Inner loop — tool planning, agentic execution, overflow."""
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
        all_tool_names = self.config.get_resolved_tools()
        all_tool_defs = get_tool_definitions(all_tool_names)
        server_tools = get_server_tools(self.config.server_tools)

        # Layer 1: Tool Planner — select relevant tools
        await emit_progress("Planning approach...")
        planned_tool_names = await self._plan_tools(user_message, all_tool_names, all_tool_defs)
        tool_defs = get_tool_definitions(planned_tool_names)
        if len(planned_tool_names) < len(all_tool_names):
            await emit_progress(f"Selected {len(planned_tool_names)} tools, starting work...")

        # Layer 2: Agentic loop (Anthropic executor)
        start_time = time.time()
        attempted_capability_recovery = False
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
                final_text = "\n".join(text_blocks) if text_blocks else "Processed — nothing to add."

                # If the model refused due to missing capabilities, give it one forced recovery pass.
                has_capability_bootstrap = bool(
                    {"create_task_plan", "execute_task_plan", "scaffold_skill"} & set(all_tool_names)
                )
                if (
                    has_capability_bootstrap
                    and not attempted_capability_recovery
                    and _looks_like_capability_refusal(final_text)
                ):
                    attempted_capability_recovery = True
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "Do not stop at capability refusal. Use available orchestration/self-mod/code tools "
                                "to propose and execute a concrete workaround now. First report what is missing, then "
                                "attempt to scaffold/attach/execute with available tools."
                            ),
                        }
                    )
                    continue

                return final_text

            # Execute custom tool calls
            tool_results = []
            for tool_call in tool_calls:
                tool_start = time.time()
                logger.info(f"[{self.config.name}] Tool: {tool_call.name}({tool_call.input})")

                # Emit progress for this tool call
                display = _TOOL_DISPLAY_NAMES.get(tool_call.name, tool_call.name.replace("_", " ").title())
                await emit_progress(f"{display}...")

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

        # Layer 3: OpenAI overflow — continue with GPT-4.1 if enabled
        if settings.overflow_enabled and settings.openai_api_key:
            await emit_progress("Switching to extended reasoning...")
            logger.info(
                f"[{self.config.name}] Anthropic exhausted {self.config.max_iterations} iterations, "
                f"switching to OpenAI overflow ({self.config.overflow_model})"
            )
            log_activity(
                agent_name=self.config.name,
                action_type=OVERFLOW_RESPONSE,
                action_detail=f"Switching to {self.config.overflow_model} after {self.config.max_iterations} iterations",
                channel=channel,
                user_id=user_id,
                session_id=session_id,
            )

            try:
                from chief_of_staff.agent.openai_adapter import overflow_respond
                overflow_result = await overflow_respond(
                    messages=messages,
                    tools=server_tools + tool_defs,
                    system_prompt=system_prompt,
                    execute_tool_fn=execute_tool,
                    agent_name=self.config.name,
                    model=self.config.overflow_model,
                    max_iterations=self.config.overflow_iterations,
                )

                log_activity(
                    agent_name=self.config.name,
                    action_type=OVERFLOW_RESPONSE,
                    action_detail=f"Overflow completed via {self.config.overflow_model}",
                    output_summary=overflow_result[:500],
                    channel=channel,
                    user_id=user_id,
                    session_id=session_id,
                )
                return overflow_result
            except Exception as e:
                logger.error(f"OpenAI overflow failed: {e}")
                log_activity(
                    agent_name=self.config.name,
                    action_type=ERROR,
                    action_detail=f"Overflow failed: {e}",
                    channel=channel,
                    user_id=user_id,
                    session_id=session_id,
                )

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
