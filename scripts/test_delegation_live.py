#!/usr/bin/env python3
"""Live test: verify the COS agent can plan + call delegate_task.

Run: PYTHONPATH=src python3 scripts/test_delegation_live.py

This does NOT go through Discord. It directly exercises:
  1. Tool resolution (does delegate_task exist?)
  2. Tool planner (does Haiku select delegate_task for a delegation request?)
  3. Executor (does Opus actually call delegate_task?)
"""

import asyncio
import json
import os
import sys
import logging

# Ensure src is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from chief_of_staff.agent.core import Agent
from chief_of_staff.agent.registry import get_registry
from chief_of_staff.agent.tools import get_tool_definitions

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("test_delegation")


async def test_tool_resolution():
    """Step 1: Verify delegate_task is in the resolved tool set."""
    reg = get_registry()
    config = reg.get("chief_of_staff")
    tools = config.get_resolved_tools()
    logger.info(f"COS resolves {len(tools)} tools")

    assert "delegate_task" in tools, "delegate_task NOT in resolved tools!"
    assert "spawn_sub_agent_task" in tools, "spawn_sub_agent_task NOT in resolved tools!"
    logger.info("PASS: delegate_task and spawn_sub_agent_task both in tool set")
    return tools, config


async def test_tool_planner(config, all_tools):
    """Step 2: Verify the Haiku planner selects delegate_task for a delegation message."""
    agent = Agent(config)
    all_tool_defs = get_tool_definitions(all_tools)

    test_message = (
        "I want the onboarding agent to look through the google drive "
        "and get a sense of what needs to be in a corpus of knowledge doc / SOP "
        "and then email me its findings."
    )

    logger.info(f"Testing planner with: {test_message[:80]}...")
    planned = await agent._plan_tools(test_message, all_tools, all_tool_defs)

    logger.info(f"Planner selected {len(planned)}/{len(all_tools)} tools: {planned}")
    if "delegate_task" in planned or "spawn_sub_agent_task" in planned:
        logger.info("PASS: Planner included delegation tool(s)")
    else:
        logger.warning(
            "WARN: Planner did NOT include delegate_task or spawn_sub_agent_task. "
            "The model might still work because it gets all tools on fallback, "
            "but this suggests the planner prompt may need tuning for delegation."
        )
    return planned


async def test_executor_first_turn(config):
    """Step 3: Send the delegation message to Opus and see if it calls delegate_task.

    We only run 1 iteration to see the first tool call — we don't actually execute it.
    """
    import anthropic
    from chief_of_staff.config import settings
    from chief_of_staff.agent.tools import get_tool_definitions, get_server_tools

    client = anthropic.AsyncAnthropic(
        api_key=settings.anthropic_api_key,
        timeout=60.0,
    )

    all_tools = config.get_resolved_tools()
    tool_defs = get_tool_definitions(all_tools)
    server_tools = get_server_tools(config.server_tools)

    test_message = (
        "I want the onboarding agent to look through the google drive "
        "and get a sense of what needs to be in a corpus of knowledge doc / SOP "
        "and then email me its findings."
    )

    system_prompt = config.build_system_prompt()
    messages = [{"role": "user", "content": test_message}]

    logger.info(f"Calling {config.model} with {len(tool_defs)} custom tools + {len(server_tools)} server tools...")
    response = await client.messages.create(
        model=config.model,
        max_tokens=config.max_tokens,
        system=system_prompt,
        tools=server_tools + tool_defs,
        messages=messages,
    )

    logger.info(f"Response stop_reason: {response.stop_reason}")
    for block in response.content:
        if block.type == "text":
            logger.info(f"Text: {block.text[:300]}")
        elif block.type == "tool_use":
            logger.info(f"TOOL CALL: {block.name}({json.dumps(block.input)[:200]})")

    tool_calls = [b for b in response.content if b.type == "tool_use"]
    delegation_calls = [t for t in tool_calls if t.name in ("delegate_task", "spawn_sub_agent_task")]

    if delegation_calls:
        logger.info(f"PASS: Model called {delegation_calls[0].name} on first turn!")
        return True
    elif tool_calls:
        logger.warning(f"Model called {[t.name for t in tool_calls]} instead of delegate_task")
        return False
    else:
        text = " ".join(b.text for b in response.content if hasattr(b, "text"))
        if "delegate" in text.lower() or "onboarding" in text.lower():
            logger.warning(f"Model talked about delegation but didn't use the tool: {text[:200]}")
        else:
            logger.warning(f"Model gave text response without delegation: {text[:200]}")
        return False


async def main():
    print("=" * 60)
    print("Live Delegation Test — COS Agent")
    print("=" * 60)
    print()

    # Step 1: Tool resolution
    tools, config = await test_tool_resolution()
    print()

    # Step 2: Tool planner
    planned = await test_tool_planner(config, tools)
    print()

    # Step 3: Executor (1 turn)
    success = await test_executor_first_turn(config)
    print()

    print("=" * 60)
    if success:
        print("RESULT: Agent successfully calls delegate_task / spawn_sub_agent_task")
    else:
        print("RESULT: Agent did NOT call delegate_task — needs investigation")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
