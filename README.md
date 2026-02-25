# langfuse-gemini-cli

[English](README.md) | [한국어](README.ko.md)

Automatic [Langfuse](https://langfuse.com) tracing for [Gemini CLI](https://github.com/google-gemini/gemini-cli). Every agent turn, LLM call, tool execution, and session event is captured as structured traces in your Langfuse dashboard -- zero code changes required.

## Status (February 25, 2026)

- ✅ Hook pipeline verified on real Gemini CLI sessions
- ✅ Session lifecycle, turn traces, tool spans, and buffer flow validated
- ✅ LGC (`langfuse-gemini-cli`) aligned with companion repos:
  - `langfuse-oh-my-codex`
  - `langfuse-claude-code`
  - `langfuse-opencode`
- Progress docs: [English](./PROGRESS.md) | [한국어](./PROGRESS.ko.md)

## Features

- **Full event coverage** -- all 11 Gemini CLI hook events are captured
- **Per-turn tracing** -- each user prompt + assistant response becomes a Langfuse trace
- **LLM call tracking** -- before/after model calls with request, response, and token usage
- **Tool call tracking** -- before/after tool execution with inputs, outputs, and duration
- **Tool selection capture** -- tool filtering and selection decisions are recorded
- **Session lifecycle** -- session start (startup/resume/clear) and end (exit/logout) events
- **Notification capture** -- system notifications logged as independent events
- **Context compression** -- pre-compression events tracked for observability
- **Session grouping** -- traces are grouped by Gemini CLI session ID
- **Buffer-based assembly** -- events are buffered per-turn and assembled into complete traces
- **Fail-open design** -- if anything goes wrong the hook exits silently; Gemini CLI is never blocked
- **Cross-platform** -- works on macOS, Linux, and Windows
- **Dual SDK support** -- works with both langfuse `>= 3.12` (nested spans) and older versions (flat traces)

## Prerequisites

- **Gemini CLI** -- installed and working (`gemini --version` to verify)
- **Python 3.8+** -- with `pip` available (`python3 -m pip --version` to verify)
- **Langfuse account** -- [cloud.langfuse.com](https://cloud.langfuse.com) (free tier available) or a self-hosted instance

## Quick Start

```bash
# Clone and run the installer
git clone https://github.com/BAEM1N/langfuse-gemini-cli.git
cd langfuse-gemini-cli
bash install.sh
```

On Windows (PowerShell):

```powershell
git clone https://github.com/BAEM1N/langfuse-gemini-cli.git
cd langfuse-gemini-cli
.\install.ps1
```

The installer will:
1. Check Python 3.8+ is available
2. Install the `langfuse` Python package
3. Copy the hook script to `~/.gemini/hooks/`
4. Prompt you for your Langfuse credentials
5. Register all 11 hook events in `~/.gemini/settings.json`
6. Verify the installation

## Manual Setup

### 1. Install the langfuse SDK

```bash
pip install langfuse
```

### 2. Copy the hook script

```bash
mkdir -p ~/.gemini/hooks ~/.gemini/state
cp langfuse_hook.py ~/.gemini/hooks/
chmod +x ~/.gemini/hooks/langfuse_hook.py
```

### 3. Configure `~/.gemini/settings.json`

Add (or merge) the following into your settings file:

```json
{
  "hooks": {
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
  },
  "env": {
    "TRACE_TO_LANGFUSE": "true",
    "LANGFUSE_PUBLIC_KEY": "pk-lf-...",
    "LANGFUSE_SECRET_KEY": "sk-lf-...",
    "LANGFUSE_BASE_URL": "https://cloud.langfuse.com",
    "LANGFUSE_USER_ID": "your-username"
  }
}
```

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TRACE_TO_LANGFUSE` | Yes | - | Set to `"true"` to enable tracing |
| `LANGFUSE_PUBLIC_KEY` | Yes | - | Langfuse public key (or `GC_LANGFUSE_PUBLIC_KEY`) |
| `LANGFUSE_SECRET_KEY` | Yes | - | Langfuse secret key (or `GC_LANGFUSE_SECRET_KEY`) |
| `LANGFUSE_BASE_URL` | No | `https://cloud.langfuse.com` | Langfuse host URL (or `GC_LANGFUSE_BASE_URL`) |
| `LANGFUSE_USER_ID` | No | `gemini-user` | User ID for trace attribution (or `GC_LANGFUSE_USER_ID`) |
| `GC_LANGFUSE_DEBUG` | No | `false` | Set to `"true"` for verbose logging |
| `GC_LANGFUSE_MAX_CHARS` | No | `20000` | Max characters per text field before truncation |

All `LANGFUSE_*` variables also accept a `GC_LANGFUSE_*` prefix (which takes priority).

## How It Works

```
┌──────────────────────────────────────────────────────────────┐
│                       Gemini CLI                              │
│                                                               │
│  User prompt ──► Model call ──► Tool calls ──► Response       │
│       │              │              │              │           │
│       ▼              ▼              ▼              ▼           │
│  BeforeAgent    BeforeModel    BeforeTool    AfterAgent        │
│       │         AfterModel     AfterTool         │            │
│       │              │              │              │           │
│       └──────────────┴──────┬───────┘              │           │
│                             │                      │           │
│                     ┌───────▼───────┐    ┌────────▼────────┐  │
│                     │ Buffer (JSONL) │    │  Assemble Trace  │ │
│                     └───────────────┘    └────────┬─────────┘ │
│                                                   │           │
│  SessionStart ──┐                                 │           │
│  Notification ──┤ (independent events)            │           │
│  PreCompress ───┤                                 │           │
│  SessionEnd ────┘                                 │           │
└───────────────────────────────────────────────────┼───────────┘
                                                    │
                                                    ▼
                                          ┌─────────────────────┐
                                          │      Langfuse        │
                                          │                      │
                                          │  Trace (Turn 1)      │
                                          │  ├─ Agent Request     │
                                          │  ├─ LLM Call [1]      │
                                          │  │   ├─ model         │
                                          │  │   ├─ usage tokens  │
                                          │  │   └─ response      │
                                          │  ├─ Tool Selection    │
                                          │  ├─ Tool: read_file   │
                                          │  ├─ LLM Call [2]      │
                                          │  ├─ Tool: write_file  │
                                          │  └─ Agent Response    │
                                          │                      │
                                          │  Event: SessionStart  │
                                          │  Event: Notification  │
                                          │  Event: SessionEnd    │
                                          │                      │
                                          │  Session: abc123      │
                                          └─────────────────────┘
```

**Flow:**

1. Gemini CLI fires hook events at each stage of the agent loop
2. **Buffer events** (`BeforeAgent`, `BeforeModel`, `AfterModel`, `BeforeToolSelection`, `BeforeTool`, `AfterTool`) are appended to a JSONL buffer file
3. When **AfterAgent** fires (turn complete), the buffer is read, assembled into a complete trace, and sent to Langfuse
4. **Independent events** (`SessionStart`, `SessionEnd`, `Notification`, `PreCompress`) are emitted immediately
5. Each turn trace includes:
   - **Agent Request** span (user prompt from BeforeAgent)
   - **LLM Call** generation observations (with model, token usage from AfterModel)
   - **Tool Selection** spans (from BeforeToolSelection)
   - **Tool** spans (paired BeforeTool/AfterTool with inputs and outputs)
   - **Agent Response** span (final response from AfterAgent)
6. All traces share the same `session_id` for grouping

## Hook Events (11 total)

| Event | Type | Data Captured |
|-------|------|---------------|
| `SessionStart` | Independent | Session source (startup/resume/clear) |
| `BeforeAgent` | Buffered | User prompt |
| `BeforeModel` | Buffered | LLM request |
| `BeforeToolSelection` | Buffered | Available tools configuration |
| `AfterModel` | Buffered | LLM request + response + token usage |
| `BeforeTool` | Buffered | Tool name + input |
| `AfterTool` | Buffered | Tool name + input + response |
| `AfterAgent` | **Trace emit** | Prompt + response (assembles buffered events) |
| `Notification` | Independent | Notification type + message |
| `PreCompress` | Independent | Compression trigger |
| `SessionEnd` | Flush + cleanup | Exit reason + remaining buffer flush |

## Compatibility

| Component | Version |
|-----------|---------|
| Python | 3.8+ |
| langfuse SDK | 2.0+ (flat traces), 3.12+ (nested spans) |
| Gemini CLI | 0.26.0+ (hooks support) |
| OS | macOS, Linux, Windows |

## Troubleshooting

### Traces not appearing

1. Verify `TRACE_TO_LANGFUSE` is set to `"true"` in your settings
2. Check that your API keys are correct
3. Enable debug logging: set `GC_LANGFUSE_DEBUG` to `"true"`
4. Check the log file: `~/.gemini/state/langfuse_hook.log`

### Hook not firing

1. Confirm hooks are in `~/.gemini/settings.json` under all 11 event keys
2. Verify the Python path in the command is correct (`python3` vs `python`)
3. Test manually: `echo '{"hook_event_name":"SessionStart","session_id":"test"}' | python3 ~/.gemini/hooks/langfuse_hook.py`

### Duplicate traces

The hook tracks turn counts in `~/.gemini/state/langfuse_state.json`. Delete this file for a fresh start.

### Large text truncation

By default, text fields are truncated at 20,000 characters. Adjust with `GC_LANGFUSE_MAX_CHARS`:

```json
"GC_LANGFUSE_MAX_CHARS": "50000"
```

## Uninstall

1. Remove all hook entries from `~/.gemini/settings.json`
2. Delete the hook script: `rm ~/.gemini/hooks/langfuse_hook.py`
3. Optionally remove state: `rm -rf ~/.gemini/state/langfuse_*`

## License

[MIT](LICENSE)
