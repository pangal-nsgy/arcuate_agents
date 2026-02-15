# Arcuate Agentic Workforce — Architecture

## Overview

The Arcuate Workforce is a multi-agent system that serves as the operating layer for Arcuate Health. The Chief of Staff (COS) orchestrates specialist agents, each with focused skills. All agents share a unified knowledge base, and the Discord bot routes messages to the right agent automatically.

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   FOUNDER INTERFACES                         │
│  Discord Bot  │  SMS (Twilio)  │  Voice (11Labs)  │  Web UI │
└───────────────┬──────────────┬─────────────────────┴────────┘
                │              │
                ▼              ▼
┌─────────────────────────────────────────────────────────────┐
│  ROUTER (router.py)                                         │
│  1. @discord_name mention → specialist                      │
│  2. Trigger word match → specialist                         │
│  3. Default → Chief of Staff                                │
└───────────────┬──────────────┬──────────────────────────────┘
                │              │
    ┌───────────▼───┐    ┌────▼────────────────┐
    │  Chief of     │    │  Onboarding         │    (future agents)
    │  Staff        │    │  Specialist         │
    │  @angie       │    │  @onboarding        │
    │               │    │                     │
    │  Skills:      │    │  Skills:            │
    │  knowledge    │    │  knowledge          │
    │  memory       │    │  communication      │
    │  delegation   │    │  memory             │
    │  self_mod     │    │                     │
    │  code_ops     │    │  8 tools            │
    │               │    │                     │
    │  13 tools     │    └─────────────────────┘
    └───────┬───────┘
            │ delegate_task
            ▼
┌─────────────────────────────────────────────────────────────┐
│  SKILL MODULES (src/chief_of_staff/agent/skills/)           │
│  ┌──────────┐ ┌──────────────┐ ┌──────────┐ ┌───────────┐ │
│  │knowledge │ │communication │ │ meetings │ │ self_mod  │ │
│  │ 3 tools  │ │   3 tools    │ │  1 tool  │ │  3 tools  │ │
│  └──────────┘ └──────────────┘ └──────────┘ └───────────┘ │
│  ┌──────────┐ ┌──────────────┐ ┌──────────────────────────┐│
│  │ memory   │ │  delegation  │ │      code_ops            ││
│  │ 2 tools  │ │   2 tools    │ │       3 tools            ││
│  └──────────┘ └──────────────┘ └──────────────────────────┘│
└──────────┬──────────────────────────────────────────────────┘
           │
┌──────────▼──────────────────────────────────────────────────┐
│  KNOWLEDGE STORE (src/chief_of_staff/knowledge/)            │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐     │
│  │  ChromaDB    │  │  SQLite      │  │  File Store   │     │
│  │  (Semantic)  │  │  (Metadata)  │  │  (Raw Docs)   │     │
│  └──────────────┘  └──────────────┘  └───────────────┘     │
└──────────┬──────────────────────────────────────────────────┘
           │
┌──────────▼──────────────────────────────────────────────────┐
│  INGESTION LAYER (src/chief_of_staff/ingestion/)            │
│  ┌──────────┐ ┌────────┐ ┌──────────┐ ┌──────────────────┐ │
│  │  Gmail   │ │ Google │ │ 11Labs   │ │ Zoom/Meeting     │ │
│  │  Sync    │ │  Docs  │ │Transcripts││  Recorder        │ │
│  └──────────┘ └────────┘ └──────────┘ └──────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

## Agent Workforce

| Agent | Discord Name | Skills | Effective Tools | Role |
|-------|-------------|--------|----------------|------|
| Chief of Staff | @angie | knowledge, memory, delegation, self_mod, code_ops | 13 + web_search | Orchestrator: delegates to specialists, handles strategy, system config, code changes |
| Onboarding Specialist | @onboarding | knowledge, communication, memory | 8 | New practice onboarding: welcome packets, checklists, emails, follow-ups |

## Skill System

Skills are reusable tool modules. Each agent loads skills by name in their YAML config. The `SkillRegistry` resolves skill names into tool definitions at runtime.

| Skill | Tools | Description |
|-------|-------|-------------|
| `knowledge` | search_knowledge, list_recent_emails, search_meetings | Search company knowledge base |
| `communication` | send_sms, send_email, draft_document | External communications |
| `meetings` | send_meeting_bot | Meeting recording bots |
| `self_mod` | update_own_instructions, update_system_prompt, update_triage_config | Self-modification |
| `memory` | remember, recall_memory | Persistent memory |
| `delegation` | create_sub_agent, delegate_task | Agent orchestration |
| `code_ops` | read_own_code, edit_own_code, deploy_changes | Code self-modification via GitHub |

## Message Flow

1. User sends Discord message
2. Bot checks: DM / @mention → always respond; otherwise → triage (merged trigger words + LLM)
3. Router resolves which agent handles: @discord_name → specialist; trigger word → specialist; default → COS
4. Agent loads its skills, builds system prompt + memory + KB context
5. Agentic loop: Claude API → tool calls → results → repeat until text response
6. Response sent to Discord, activity logged with resolved agent_name

## Tech Stack

- **Language**: Python 3.12
- **Framework**: FastAPI (webhook server + API)
- **LLM**: Anthropic Claude (Sonnet 4.5 for agents, Haiku 4.5 for triage)
- **Vector DB**: ChromaDB (local, upgradeable to Pinecone)
- **Database**: SQLite (local, Railway persistent volume)
- **Deployment**: Railway (auto-deploy from GitHub push)
- **Integrations**: Google APIs, Twilio, ElevenLabs, Discord, Zoom/Recall.ai

## Adding a New Agent

1. Create `agents/<name>.yaml` — define name, discord_name, skills, system_prompt, permissions
2. Create `agent_memory/<name>.md` (empty)
3. The registry auto-discovers it. Router picks it up for discord_name and trigger_words.
4. No code changes needed.

## Adding a New Skill

1. Create `src/chief_of_staff/agent/skills/<name>.py`
2. Export: `SKILL_NAME`, `TOOL_DEFINITIONS`, `async execute()`
3. Add module name to `_SKILL_MODULES` in `skills/__init__.py`
4. Add to agents' `skills:` list in YAML
