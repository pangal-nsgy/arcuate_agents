"""Code operations skill — read, edit, deploy own source code via GitHub."""

from __future__ import annotations

from typing import Any

SKILL_NAME = "code_ops"

TOOL_DEFINITIONS: dict[str, dict[str, Any]] = {
    "read_own_code": {
        "name": "read_own_code",
        "description": "Read any file in the repo from GitHub. Use this to inspect your own source code, configs, or other project files before making changes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path relative to repo root (e.g. 'src/chief_of_staff/agent/tools.py')"},
            },
            "required": ["path"],
        },
    },
    "edit_own_code": {
        "name": "edit_own_code",
        "description": "Stage an edit to a file in the repo. The file is syntax-validated (Python/YAML) and added to a staging area. Use deploy_changes to commit and push all staged edits. Blocked paths (.env, credentials, databases) are rejected.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path relative to repo root"},
                "content": {"type": "string", "description": "The complete new file content"},
                "reason": {"type": "string", "description": "Brief explanation of what changed and why (logged for audit)"},
            },
            "required": ["path", "content", "reason"],
        },
    },
    "deploy_changes": {
        "name": "deploy_changes",
        "description": "Commit and push all staged code edits to GitHub as one atomic commit. Railway auto-deploys from the push. Use edit_own_code to stage files first.",
        "input_schema": {
            "type": "object",
            "properties": {
                "commit_message": {"type": "string", "description": "Git commit message describing the changes"},
            },
            "required": ["commit_message"],
        },
    },
}


async def execute(name: str, args: dict[str, Any], agent_name: str) -> str:
    """Execute a code ops tool. May raise — caller handles exceptions."""
    if name == "read_own_code":
        from chief_of_staff.agent.activity import log_activity, CODE_READ
        from chief_of_staff.agent.registry import get_registry
        from chief_of_staff.agent.code_ops import read_file_from_github

        registry = get_registry()
        config = registry.get(agent_name)
        if config and not config.permissions.get("can_modify_code"):
            return "Error: this agent does not have permission to read code."

        path = args["path"]
        result = await read_file_from_github(path)

        log_activity(
            agent_name=agent_name,
            action_type=CODE_READ,
            action_detail=path,
            output_summary=f"{len(result.get('content', ''))} chars" if "content" in result else result.get("error", ""),
        )

        if "error" in result:
            return f"Error: {result['error']}"
        return f"File: {path} ({len(result['content'])} chars)\n\n{result['content']}"

    elif name == "edit_own_code":
        from chief_of_staff.agent.activity import log_activity, CODE_EDIT
        from chief_of_staff.agent.registry import get_registry
        from chief_of_staff.agent.code_ops import stage_file, get_staged_summary

        registry = get_registry()
        config = registry.get(agent_name)
        if config and not config.permissions.get("can_modify_code"):
            return "Error: this agent does not have permission to edit code."

        path = args.get("path", "")
        content = args.get("content", "")
        reason = args.get("reason", "no reason given")

        if not path:
            return "Error: 'path' is required."
        if not content:
            return "Error: 'content' is required — provide the complete new file content."

        result = stage_file(path, content)

        log_activity(
            agent_name=agent_name,
            action_type=CODE_EDIT,
            action_detail=f"{path}: {reason}",
            input_summary=f"{len(content)} chars",
            output_summary=result,
        )

        return f"{result}\n\n{get_staged_summary()}"

    elif name == "deploy_changes":
        from chief_of_staff.agent.activity import log_activity, CODE_DEPLOY
        from chief_of_staff.agent.registry import get_registry
        from chief_of_staff.agent.code_ops import deploy_changes as _deploy

        registry = get_registry()
        config = registry.get(agent_name)
        if config and not config.permissions.get("can_modify_code"):
            return "Error: this agent does not have permission to deploy code."

        commit_msg = args["commit_message"]

        try:
            result = await _deploy(commit_msg)
        except Exception as e:
            log_activity(
                agent_name=agent_name,
                action_type=CODE_DEPLOY,
                action_detail=f"FAILED: {e}",
                input_summary=commit_msg,
            )
            return f"Error deploying: {e}"

        if "error" in result:
            log_activity(
                agent_name=agent_name,
                action_type=CODE_DEPLOY,
                action_detail=f"FAILED: {result['error']}",
                input_summary=commit_msg,
            )
            return f"Error: {result['error']}"

        log_activity(
            agent_name=agent_name,
            action_type=CODE_DEPLOY,
            action_detail=f"commit {result['commit_sha'][:8]}",
            input_summary=commit_msg,
            output_summary=f"Deployed {len(result['files'])} file(s): {result['files']}",
            metadata={"commit_sha": result["commit_sha"], "files": result["files"]},
        )

        return (
            f"Deployed successfully!\n"
            f"Commit: {result['commit_sha'][:8]}\n"
            f"Files: {', '.join(result['files'])}\n"
            f"Message: {result['message']}\n"
            f"Railway will auto-deploy this commit."
        )

    else:
        raise ValueError(f"Unknown code_ops tool: {name}")
