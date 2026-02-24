#!/usr/bin/env bash
set -euo pipefail

# ─────────────────────────────────────────────
# langfuse-gemini-cli installer (macOS / Linux)
# ─────────────────────────────────────────────

HOOK_NAME="langfuse_hook.py"
GEMINI_DIR="$HOME/.gemini"
HOOKS_DIR="$GEMINI_DIR/hooks"
STATE_DIR="$GEMINI_DIR/state"
SETTINGS_FILE="$GEMINI_DIR/settings.json"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }
step()  { echo -e "${BLUE}[STEP]${NC} $1"; }

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║  langfuse-gemini-cli installer           ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ── 1. Check Python ──────────────────────────
step "Checking Python installation..."
PYTHON=""
if command -v python3 &>/dev/null; then
    PYTHON="python3"
elif command -v python &>/dev/null; then
    PYTHON="python"
else
    error "Python not found. Please install Python 3.8+ first."
    exit 1
fi

PY_VERSION=$($PYTHON -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$($PYTHON -c 'import sys; print(sys.version_info.major)')
PY_MINOR=$($PYTHON -c 'import sys; print(sys.version_info.minor)')

if [[ "$PY_MAJOR" -lt 3 ]] || { [[ "$PY_MAJOR" -eq 3 ]] && [[ "$PY_MINOR" -lt 8 ]]; }; then
    error "Python 3.8+ required, found $PY_VERSION"
    exit 1
fi

info "Found $PYTHON ($PY_VERSION)"

# ── 2. Check Gemini CLI ─────────────────────
step "Checking Gemini CLI installation..."
if command -v gemini &>/dev/null; then
    info "Gemini CLI found: $(command -v gemini)"
else
    warn "Gemini CLI not found in PATH. Make sure it's installed before using the hook."
fi

# ── 3. Install langfuse SDK ──────────────────
step "Installing langfuse Python SDK..."
$PYTHON -m pip install --quiet --upgrade langfuse
info "langfuse SDK installed."

# ── 4. Copy hook script ─────────────────────
step "Copying hook script..."
mkdir -p "$HOOKS_DIR"
mkdir -p "$STATE_DIR"
cp "$SCRIPT_DIR/$HOOK_NAME" "$HOOKS_DIR/$HOOK_NAME"
chmod +x "$HOOKS_DIR/$HOOK_NAME"
info "Hook script installed: $HOOKS_DIR/$HOOK_NAME"

# ── 5. Clean previous state (optional) ──────
if [[ -f "$STATE_DIR/langfuse_state.json" ]]; then
    echo ""
    read -rp "  Previous state file found. Reset trace offsets? [y/N]: " RESET_STATE
    if [[ "${RESET_STATE,,}" == "y" ]]; then
        rm -f "$STATE_DIR/langfuse_state.json"
        rm -f "$STATE_DIR"/langfuse_buffer_*.jsonl
        info "State files reset."
    fi
fi

# ── 6. Collect Langfuse credentials ─────────
echo ""
step "Configuring Langfuse credentials..."
echo "  Get your keys from https://cloud.langfuse.com (or your self-hosted instance)."
echo ""

read -rp "  Langfuse Public Key  : " LF_PUBLIC_KEY
read -rsp "  Langfuse Secret Key  : " LF_SECRET_KEY
echo ""
read -rp "  Langfuse Base URL    [https://cloud.langfuse.com]: " LF_BASE_URL
LF_BASE_URL="${LF_BASE_URL:-https://cloud.langfuse.com}"

read -rp "  User ID (trace attribution) [gemini-user]: " LF_USER_ID
LF_USER_ID="${LF_USER_ID:-gemini-user}"

if [[ -z "$LF_PUBLIC_KEY" || -z "$LF_SECRET_KEY" ]]; then
    error "Public Key and Secret Key are required."
    exit 1
fi

# ── 7. Write credentials to .env ──────────────
step "Writing credentials to $GEMINI_DIR/.env..."
ENV_FILE="$GEMINI_DIR/.env"
mkdir -p "$GEMINI_DIR"

cat > "$ENV_FILE" <<ENVEOF
# Langfuse credentials for langfuse-gemini-cli
# Environment variables and settings.json env take priority over .env values.

TRACE_TO_LANGFUSE=true
LANGFUSE_PUBLIC_KEY=${LF_PUBLIC_KEY}
LANGFUSE_SECRET_KEY=${LF_SECRET_KEY}
LANGFUSE_BASE_URL=${LF_BASE_URL}
LANGFUSE_USER_ID=${LF_USER_ID}
ENVEOF

info "Credentials written to $ENV_FILE"

# ── 8. Merge hooks into settings.json ─────────
step "Updating $SETTINGS_FILE (hooks only, credentials in .env)..."

HOOK_CMD="$PYTHON ~/.gemini/hooks/langfuse_hook.py"

# Smart merge: preserves existing hooks/env, only adds hooks + TRACE_TO_LANGFUSE
$PYTHON - "$SETTINGS_FILE" "$HOOK_CMD" <<'PYEOF'
import json, sys, os

settings_path = sys.argv[1]
hook_command  = sys.argv[2]

# Load existing settings
if os.path.exists(settings_path):
    with open(settings_path, "r", encoding="utf-8") as f:
        settings = json.load(f)
else:
    settings = {}

# ── Merge env (only TRACE_TO_LANGFUSE; credentials stay in .env) ──
if "env" not in settings or not isinstance(settings["env"], dict):
    settings["env"] = {}
settings["env"]["TRACE_TO_LANGFUSE"] = "true"

# ── Merge hooks (preserve existing hooks) ──
if "hooks" not in settings or not isinstance(settings["hooks"], dict):
    settings["hooks"] = {}

langfuse_entry = {
    "hooks": [{"type": "command", "command": hook_command}]
}

ALL_EVENTS = [
    "SessionStart", "BeforeAgent", "BeforeModel", "BeforeToolSelection",
    "AfterModel", "BeforeTool", "AfterTool", "AfterAgent",
    "Notification", "PreCompress", "SessionEnd",
]

def upsert_hook(settings, event_name, langfuse_entry):
    hook_list = settings["hooks"].get(event_name, [])
    if not isinstance(hook_list, list):
        hook_list = []
    replaced = False
    for i, entry in enumerate(hook_list):
        if not isinstance(entry, dict):
            continue
        for h in entry.get("hooks", []):
            if isinstance(h, dict) and "langfuse_hook" in h.get("command", ""):
                hook_list[i] = langfuse_entry
                replaced = True
                break
        if replaced:
            break
    if not replaced:
        hook_list.append(langfuse_entry)
    settings["hooks"][event_name] = hook_list
    return len(hook_list), replaced

results = []
for event in ALL_EVENTS:
    n, replaced = upsert_hook(settings, event, langfuse_entry)
    results.append((event, n, replaced))

# Write
with open(settings_path, "w", encoding="utf-8") as f:
    json.dump(settings, f, indent=2, ensure_ascii=False)
    f.write("\n")

print(f"  Settings written to {settings_path}")
for event, n, replaced in results:
    status = "updated" if replaced else "added"
    print(f"  {event}: {n} hook(s) ({status} langfuse)")
PYEOF

# ── 9. Verify ────────────────────────────────
step "Verifying installation..."
if $PYTHON -c "import langfuse" 2>/dev/null; then
    info "langfuse SDK: OK"
else
    warn "langfuse SDK import failed. Check your Python environment."
fi

if [[ -f "$HOOKS_DIR/$HOOK_NAME" ]]; then
    info "Hook script: OK"
else
    warn "Hook script not found at $HOOKS_DIR/$HOOK_NAME"
fi

# ── Done ─────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════╗"
echo "║  Installation complete!                  ║"
echo "╚══════════════════════════════════════════╝"
echo ""
info "Gemini CLI will now send traces to Langfuse on all 11 hook events."
info "Start (or restart) Gemini CLI to activate the hooks."
echo ""
echo "  Dashboard : ${LF_BASE_URL}"
echo "  Logs      : ~/.gemini/state/langfuse_hook.log"
echo "  Debug     : set GC_LANGFUSE_DEBUG=true in settings.json env"
echo "  Disable   : set TRACE_TO_LANGFUSE=false in settings.json env"
echo ""
