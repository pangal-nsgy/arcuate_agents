"""OpenAI overflow adapter — converts Anthropic formats and runs GPT-4.1 when Anthropic exhausts iterations."""

from __future__ import annotations

import json
import logging
from typing import Any

from chief_of_staff.config import settings

logger = logging.getLogger(__name__)


def _anthropic_tool_to_openai(tool_def: dict[str, Any]) -> dict[str, Any]:
    """Convert a single Anthropic tool definition to OpenAI function-calling format."""
    # Anthropic format: {"name": ..., "description": ..., "input_schema": {...}}
    # OpenAI format:    {"type": "function", "function": {"name": ..., "description": ..., "parameters": {...}}}
    return {
        "type": "function",
        "function": {
            "name": tool_def["name"],
            "description": tool_def.get("description", ""),
            "parameters": tool_def.get("input_schema", {"type": "object", "properties": {}}),
        },
    }


def convert_tools(anthropic_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert a list of Anthropic tool definitions to OpenAI function-calling format.

    Skips server tools (type: web_search_20250305 etc.) which have no OpenAI equivalent.
    """
    openai_tools = []
    for tool in anthropic_tools:
        # Skip Anthropic server-side tools (they have 'type' at the top level, not 'name')
        if "name" not in tool:
            continue
        openai_tools.append(_anthropic_tool_to_openai(tool))
    return openai_tools


def convert_messages(
    anthropic_messages: list[dict[str, Any]],
    system_prompt: str,
) -> list[dict[str, Any]]:
    """Convert Anthropic message history to OpenAI chat format.

    Anthropic format:
      - system prompt is separate
      - assistant content is a list of ContentBlock objects (text, tool_use)
      - tool results come as user messages with tool_result blocks

    OpenAI format:
      - system prompt is a message with role="system"
      - assistant text is a string
      - tool calls are in tool_calls array
      - tool results are separate messages with role="tool"
    """
    openai_messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
    ]

    for msg in anthropic_messages:
        role = msg.get("role", "user")

        if role == "user":
            content = msg.get("content")

            # Tool results (list of tool_result dicts)
            if isinstance(content, list) and content and isinstance(content[0], dict) and content[0].get("type") == "tool_result":
                for tr in content:
                    openai_messages.append({
                        "role": "tool",
                        "tool_call_id": tr.get("tool_use_id", ""),
                        "content": tr.get("content", ""),
                    })
            # Plain text user message
            elif isinstance(content, str):
                openai_messages.append({"role": "user", "content": content})
            else:
                # Fallback — stringify
                openai_messages.append({"role": "user", "content": str(content)})

        elif role == "assistant":
            content = msg.get("content")

            # Content is a list of Anthropic ContentBlock objects
            if isinstance(content, list):
                text_parts = []
                tool_calls = []

                for block in content:
                    # Anthropic returns objects with .type, .text, .name, .input, .id
                    block_type = getattr(block, "type", None) or (block.get("type") if isinstance(block, dict) else None)

                    if block_type == "text":
                        text = getattr(block, "text", None) or (block.get("text", "") if isinstance(block, dict) else "")
                        text_parts.append(text)
                    elif block_type == "tool_use":
                        name = getattr(block, "name", None) or (block.get("name", "") if isinstance(block, dict) else "")
                        inp = getattr(block, "input", None) or (block.get("input", {}) if isinstance(block, dict) else {})
                        tool_id = getattr(block, "id", None) or (block.get("id", "") if isinstance(block, dict) else "")
                        tool_calls.append({
                            "id": tool_id,
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(inp) if isinstance(inp, dict) else str(inp),
                            },
                        })

                assistant_msg: dict[str, Any] = {"role": "assistant"}
                if text_parts:
                    assistant_msg["content"] = "\n".join(text_parts)
                else:
                    assistant_msg["content"] = None
                if tool_calls:
                    assistant_msg["tool_calls"] = tool_calls

                openai_messages.append(assistant_msg)
            elif isinstance(content, str):
                openai_messages.append({"role": "assistant", "content": content})

    return openai_messages


async def overflow_respond(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    system_prompt: str,
    execute_tool_fn: Any,
    agent_name: str = "chief_of_staff",
    model: str = "",
    max_iterations: int = 10,
) -> str:
    """Run an overflow agentic loop using OpenAI GPT-4.1.

    Args:
        messages: Anthropic-format message history
        tools: Anthropic-format tool definitions (will be converted)
        system_prompt: The system prompt
        execute_tool_fn: async callable(name, args, agent_name) -> str
        agent_name: For activity logging
        model: OpenAI model to use (defaults to settings.openai_model)
        max_iterations: Max turns for the overflow loop

    Returns:
        The final text response from GPT-4.1
    """
    import openai

    api_key = settings.openai_api_key
    if not api_key:
        return "Overflow unavailable — OPENAI_API_KEY not configured."

    client = openai.AsyncOpenAI(api_key=api_key, timeout=60.0)
    model = model or settings.openai_model

    # Convert formats
    openai_tools = convert_tools(tools)
    openai_messages = convert_messages(messages, system_prompt)

    # Add a continuation note so GPT-4.1 knows to continue
    openai_messages.append({
        "role": "user",
        "content": (
            "[System note: The previous model reached its iteration limit. "
            "Continue the task from where it left off. Use the available tools to complete the request.]"
        ),
    })

    for iteration in range(max_iterations):
        try:
            kwargs: dict[str, Any] = {
                "model": model,
                "messages": openai_messages,
                "max_tokens": 16384,
            }
            if openai_tools:
                kwargs["tools"] = openai_tools
                kwargs["tool_choice"] = "auto"

            response = await client.chat.completions.create(**kwargs)
        except Exception as e:
            logger.error(f"OpenAI overflow API error: {e}")
            return f"Overflow error: {e}"

        choice = response.choices[0]
        message = choice.message

        # Append assistant message
        assistant_msg: dict[str, Any] = {"role": "assistant", "content": message.content}
        if message.tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in message.tool_calls
            ]
        openai_messages.append(assistant_msg)

        # If no tool calls, return the text response
        if not message.tool_calls:
            return message.content or "Processed — nothing to add."

        # Execute tool calls
        for tc in message.tool_calls:
            try:
                args = json.loads(tc.function.arguments)
            except (json.JSONDecodeError, TypeError):
                args = {}

            logger.info(f"[overflow/{agent_name}] Tool: {tc.function.name}({args})")

            try:
                result = await execute_tool_fn(tc.function.name, args, agent_name=agent_name)
            except Exception as e:
                result = f"Tool error: {e}"

            openai_messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

    return "Hit overflow limit. Try breaking down the request further."
