# Agent Setup Guide

This file helps AI coding agents (Claude Code, Gemini CLI, Cursor, etc.) automatically set up langfuse-gemini-cli for the user.

## Project Overview

**langfuse-gemini-cli** traces Gemini CLI conversations to Langfuse. It hooks into all 11 Gemini CLI events for comprehensive observability: session lifecycle, agent turns, LLM calls, tool selection, tool execution, notifications, and context compression.

## Automated Setup Procedure

When a user asks to set up this project, follow these steps:

### Step 1: Check Prerequisites

```bash
# Python 3.8+
python3 --version

# pip available
python3 -m pip --version

# Gemini CLI installed
gemini --version

# langfuse SDK
python3 -c "import langfuse; print(langfuse.__version__)" 2>/dev/null || echo "Not installed"
```

If langfuse is not installed:
```bash
python3 -m pip install --upgrade langfuse
```

### Step 2: Interview User for Langfuse Credentials

Ask the user for these values. Do NOT guess or use placeholder values.

| Key | Question to Ask | Example Format |
|-----|-----------------|----------------|
| `LANGFUSE_PUBLIC_KEY` | "Langfuse Public Key를 알려주세요" | `pk-lf-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` |
| `LANGFUSE_SECRET_KEY` | "Langfuse Secret Key를 알려주세요" | `sk-lf-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` |
| `LANGFUSE_BASE_URL` | "Langfuse URL을 알려주세요 (기본값: https://cloud.langfuse.com)" | `https://cloud.langfuse.com` or self-hosted URL |
| `LANGFUSE_USER_ID` | "트레이스에 표시할 사용자 ID를 알려주세요 (기본값: gemini-user)" | Any string |

Get keys from: https://cloud.langfuse.com → Project Settings → API Keys

### Step 3: Install Hook Script

```bash
mkdir -p ~/.gemini/hooks ~/.gemini/state
cp langfuse_hook.py ~/.gemini/hooks/langfuse_hook.py
chmod +x ~/.gemini/hooks/langfuse_hook.py
```

### Step 4: Write Credentials to .env

Write the credentials to `~/.gemini/.env` (user-level, NOT in settings.json):

```bash
cat > ~/.gemini/.env <<EOF
# Langfuse credentials for langfuse-gemini-cli
# Environment variables and settings.json env take priority over .env values.

TRACE_TO_LANGFUSE=true
LANGFUSE_PUBLIC_KEY=<from interview>
LANGFUSE_SECRET_KEY=<from interview>
LANGFUSE_BASE_URL=<from interview>
LANGFUSE_USER_ID=<from interview>
EOF
```

### Step 5: Configure settings.json

Read the existing `~/.gemini/settings.json` first, then merge (do NOT overwrite existing settings):

**Add to `env`** (only the enable flag; credentials are in .env):
```json
{
  "TRACE_TO_LANGFUSE": "true"
}
```

**Add to `hooks`** (preserve existing hooks, register all 11 events):
```json
{
  "SessionStart": [{"hooks": [{"type": "command", "command": "python3 ~/.gemini/hooks/langfuse_hook.py"}]}],
  "BeforeAgent": [{"hooks": [{"type": "command", "command": "python3 ~/.gemini/hooks/langfuse_hook.py"}]}],
  "BeforeModel": [{"hooks": [{"type": "command", "command": "python3 ~/.gemini/hooks/langfuse_hook.py"}]}],
  "BeforeToolSelection": [{"hooks": [{"type": "command", "command": "python3 ~/.gemini/hooks/langfuse_hook.py"}]}],
  "AfterModel": [{"hooks": [{"type": "command", "command": "python3 ~/.gemini/hooks/langfuse_hook.py"}]}],
  "BeforeTool": [{"hooks": [{"type": "command", "command": "python3 ~/.gemini/hooks/langfuse_hook.py"}]}],
  "AfterTool": [{"hooks": [{"type": "command", "command": "python3 ~/.gemini/hooks/langfuse_hook.py"}]}],
  "AfterAgent": [{"hooks": [{"type": "command", "command": "python3 ~/.gemini/hooks/langfuse_hook.py"}]}],
  "Notification": [{"hooks": [{"type": "command", "command": "python3 ~/.gemini/hooks/langfuse_hook.py"}]}],
  "PreCompress": [{"hooks": [{"type": "command", "command": "python3 ~/.gemini/hooks/langfuse_hook.py"}]}],
  "SessionEnd": [{"hooks": [{"type": "command", "command": "python3 ~/.gemini/hooks/langfuse_hook.py"}]}]
}
```

### Step 6: Verify

```bash
# Check hook file exists
ls -la ~/.gemini/hooks/langfuse_hook.py

# Check .env file exists
ls -la ~/.gemini/.env

# Check langfuse import works
python3 -c "import langfuse; print('OK')"

# Dry-run test (should output {"decision": "allow"} and exit)
echo '{"hook_event_name":"SessionStart","session_id":"test"}' | python3 ~/.gemini/hooks/langfuse_hook.py
```

### Step 7: Inform User

Tell the user:
- Restart Gemini CLI to activate the hooks
- Dashboard: the LANGFUSE_BASE_URL they provided
- Credentials: `~/.gemini/.env`
- Logs: `~/.gemini/state/langfuse_hook.log`
- Debug mode: set `GC_LANGFUSE_DEBUG` to `"true"` in .env or settings.json env
- Disable: set `TRACE_TO_LANGFUSE` to `"false"` in settings.json env

## Configuration Hierarchy

Priority (highest first):
1. **Environment variables** (system-level)
2. **settings.json `env` section** (project-level config)
3. **~/.gemini/.env** (user-level credentials)

Credentials go in `.env`, hook registration and feature flags go in `settings.json`.

## Architecture

```
Hook Events Flow:
  BeforeAgent ──┐
  BeforeModel ──┤
  AfterModel  ──┤── Buffer (JSONL) ──► AfterAgent ──► Langfuse Trace
  BeforeTool  ──┤
  AfterTool   ──┤
  BeforeToolSelection ──┘

  SessionStart ──► Langfuse Event (independent)
  SessionEnd   ──► Flush buffer + Langfuse Event
  Notification ──► Langfuse Event (independent)
  PreCompress  ──► Langfuse Event (independent)
```

## File Paths

| File | Path | Purpose |
|------|------|---------|
| Hook script (source) | `./langfuse_hook.py` | Main hook implementation |
| Hook script (installed) | `~/.gemini/hooks/langfuse_hook.py` | Active hook |
| Credentials | `~/.gemini/.env` | Langfuse API keys (user-level) |
| Settings | `~/.gemini/settings.json` | Hook registration + feature flags |
| State | `~/.gemini/state/langfuse_state.json` | Turn count tracking |
| Buffer | `~/.gemini/state/langfuse_buffer_*.jsonl` | Event accumulation per session |
| Log | `~/.gemini/state/langfuse_hook.log` | Hook execution log |

## Hook Events Reference (11 total)

| Event | Payload Fields | Langfuse Type |
|-------|---------------|---------------|
| `SessionStart` | `source` | Independent event |
| `BeforeAgent` | `prompt` | Buffered → Agent Request span |
| `BeforeModel` | `llm_request` | Buffered → part of Generation |
| `BeforeToolSelection` | `llm_request` | Buffered → Tool Selection span |
| `AfterModel` | `llm_request`, `llm_response` | Buffered → Generation observation |
| `BeforeTool` | `tool_name`, `tool_input` | Buffered → paired with AfterTool |
| `AfterTool` | `tool_name`, `tool_input`, `tool_response` | Buffered → Tool span |
| `AfterAgent` | `prompt`, `prompt_response` | **Trace emit** (assembles buffer) |
| `Notification` | `notification_type`, `message`, `details` | Independent event |
| `PreCompress` | `trigger` | Independent event |
| `SessionEnd` | `reason` | Flush + cleanup |

## Troubleshooting

- **No traces**: Check `TRACE_TO_LANGFUSE=true` and API keys in `~/.gemini/.env`
- **Hook not firing**: Verify hooks are in settings.json under all 11 event keys
- **Import error**: Run `python3 -m pip install langfuse`
- **Buffer not clearing**: Check `~/.gemini/state/` for stale buffer files
- **Gemini CLI version**: Hooks require v0.26.0+ (`gemini --version`)
