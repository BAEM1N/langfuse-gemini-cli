# ─────────────────────────────────────────────
# langfuse-gemini-cli installer (Windows)
# ─────────────────────────────────────────────

$ErrorActionPreference = "Stop"

$HOOK_NAME    = "langfuse_hook.py"
$GEMINI_DIR   = Join-Path $env:USERPROFILE ".gemini"
$HOOKS_DIR    = Join-Path $GEMINI_DIR "hooks"
$STATE_DIR    = Join-Path $GEMINI_DIR "state"
$SETTINGS     = Join-Path $GEMINI_DIR "settings.json"
$SCRIPT_DIR   = Split-Path -Parent $MyInvocation.MyCommand.Path

function Info  ($msg) { Write-Host "[INFO] $msg"  -ForegroundColor Green  }
function Warn  ($msg) { Write-Host "[WARN] $msg"  -ForegroundColor Yellow }
function Err   ($msg) { Write-Host "[ERROR] $msg" -ForegroundColor Red    }
function Step  ($msg) { Write-Host "[STEP] $msg"  -ForegroundColor Cyan   }

Write-Host ""
Write-Host "=========================================="
Write-Host "  langfuse-gemini-cli installer"
Write-Host "=========================================="
Write-Host ""

# ── 1. Python check ──
Step "Checking Python..."
$py = $null
foreach ($cmd in @("python3", "python")) {
    try { & $cmd --version 2>$null | Out-Null; $py = $cmd; break } catch {}
}
if (-not $py) { Err "Python 3.8+ not found."; exit 1 }

$ver = & $py -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
$major = & $py -c "import sys; print(sys.version_info.major)"
$minor = & $py -c "import sys; print(sys.version_info.minor)"
if ([int]$major -lt 3 -or ([int]$major -eq 3 -and [int]$minor -lt 8)) {
    Err "Python 3.8+ required, found $ver"; exit 1
}
Info "Found $py ($ver)"

# ── 2. Gemini CLI check ──
Step "Checking Gemini CLI..."
try {
    $geminiPath = Get-Command gemini -ErrorAction SilentlyContinue
    if ($geminiPath) { Info "Gemini CLI found: $($geminiPath.Source)" }
    else { Warn "Gemini CLI not found in PATH." }
} catch { Warn "Gemini CLI not found in PATH." }

# ── 3. Install SDK ──
Step "Installing langfuse SDK..."
& $py -m pip install --quiet --upgrade langfuse
Info "langfuse SDK installed."

# ── 4. Copy hook ──
Step "Copying hook script..."
New-Item -ItemType Directory -Force -Path $HOOKS_DIR | Out-Null
New-Item -ItemType Directory -Force -Path $STATE_DIR | Out-Null
Copy-Item (Join-Path $SCRIPT_DIR $HOOK_NAME) (Join-Path $HOOKS_DIR $HOOK_NAME) -Force
Info "Hook installed: $HOOKS_DIR\$HOOK_NAME"

# ── 5. State reset ──
$stateFile = Join-Path $STATE_DIR "langfuse_state.json"
if (Test-Path $stateFile) {
    $reset = Read-Host "  Previous state found. Reset? [y/N]"
    if ($reset -eq "y") {
        Remove-Item $stateFile -Force
        Get-ChildItem (Join-Path $STATE_DIR "langfuse_buffer_*.jsonl") -ErrorAction SilentlyContinue | Remove-Item -Force
        Info "State reset."
    }
}

# ── 6. Credentials ──
Write-Host ""
Step "Configuring Langfuse credentials..."
Write-Host "  Get keys from https://cloud.langfuse.com"
Write-Host ""

$pk  = Read-Host "  Public Key"
$sk  = Read-Host "  Secret Key" -AsSecureString
$skPlain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sk))
$url = Read-Host "  Base URL [https://cloud.langfuse.com]"
if (-not $url) { $url = "https://cloud.langfuse.com" }
$uid = Read-Host "  User ID [gemini-user]"
if (-not $uid) { $uid = "gemini-user" }

if (-not $pk -or -not $skPlain) { Err "Keys required."; exit 1 }

# ── 7. Merge settings ──
Step "Updating settings.json..."
New-Item -ItemType Directory -Force -Path $GEMINI_DIR | Out-Null

$hookCmd = "$py ~/.gemini/hooks/langfuse_hook.py"
& $py - $SETTINGS $hookCmd $pk $skPlain $url $uid @'
import json, sys, os

settings_path, hook_command, public_key, secret_key, base_url, user_id = sys.argv[1:7]

if os.path.exists(settings_path):
    with open(settings_path, "r", encoding="utf-8") as f:
        settings = json.load(f)
else:
    settings = {}

if "env" not in settings or not isinstance(settings["env"], dict):
    settings["env"] = {}
settings["env"]["TRACE_TO_LANGFUSE"]  = "true"
settings["env"]["LANGFUSE_PUBLIC_KEY"] = public_key
settings["env"]["LANGFUSE_SECRET_KEY"] = secret_key
settings["env"]["LANGFUSE_BASE_URL"]   = base_url
settings["env"]["LANGFUSE_USER_ID"]    = user_id

if "hooks" not in settings or not isinstance(settings["hooks"], dict):
    settings["hooks"] = {}

langfuse_entry = {"hooks": [{"type": "command", "command": hook_command}]}

ALL_EVENTS = [
    "SessionStart", "BeforeAgent", "BeforeModel", "BeforeToolSelection",
    "AfterModel", "BeforeTool", "AfterTool", "AfterAgent",
    "Notification", "PreCompress", "SessionEnd",
]

def upsert_hook(settings, event_name, entry):
    hook_list = settings["hooks"].get(event_name, [])
    if not isinstance(hook_list, list):
        hook_list = []
    replaced = False
    for i, e in enumerate(hook_list):
        if not isinstance(e, dict):
            continue
        for h in e.get("hooks", []):
            if isinstance(h, dict) and "langfuse_hook" in h.get("command", ""):
                hook_list[i] = entry
                replaced = True
                break
        if replaced:
            break
    if not replaced:
        hook_list.append(entry)
    settings["hooks"][event_name] = hook_list

for event in ALL_EVENTS:
    upsert_hook(settings, event, langfuse_entry)

with open(settings_path, "w", encoding="utf-8") as f:
    json.dump(settings, f, indent=2, ensure_ascii=False)
    f.write("\n")

print(f"  Settings written to {settings_path}")
print(f"  Registered {len(ALL_EVENTS)} hook events")
'@

# ── 8. Verify ──
Step "Verifying..."
try { & $py -c "import langfuse"; Info "langfuse SDK: OK" }
catch { Warn "langfuse import failed." }

if (Test-Path (Join-Path $HOOKS_DIR $HOOK_NAME)) { Info "Hook script: OK" }
else { Warn "Hook not found." }

Write-Host ""
Write-Host "=========================================="
Write-Host "  Installation complete!"
Write-Host "=========================================="
Write-Host ""
Info "Gemini CLI will now send traces to Langfuse on all 11 hook events."
Info "Restart Gemini CLI to activate."
Write-Host ""
Write-Host "  Dashboard : $url"
Write-Host "  Logs      : ~/.gemini/state/langfuse_hook.log"
Write-Host ""
