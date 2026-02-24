#!/usr/bin/env python3
"""
Gemini CLI -> Langfuse hook

Automatically traces Gemini CLI conversations to Langfuse.
Hooks into all 11 Gemini CLI events for comprehensive observability.

Captured data:
  - Session lifecycle (start, end, compression)
  - Agent turns (before/after with prompt and response)
  - LLM calls (before/after with request, response, token usage)
  - Tool selection (available tools, filtering)
  - Tool calls (before/after with inputs, outputs, duration)
  - Notifications (system alerts and messages)

Architecture:
  Before*/After* events are buffered to a JSONL file.
  AfterAgent reads the buffer, assembles a complete Langfuse trace, and emits it.
  SessionStart/End, Notification, PreCompress are emitted independently.

Usage:
  Configure as hooks in ~/.gemini/settings.json
  See README.md for full setup instructions.
"""

import json
import os
import socket
import sys
import time
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# --- Langfuse import (fail-open) ---
try:
    from langfuse import Langfuse
except Exception:
    # Output allow decision before exiting so Gemini CLI continues
    try:
        print(json.dumps({"decision": "allow"}))
    except Exception:
        pass
    sys.exit(0)

# propagate_attributes: langfuse >= 3.12 (Python >= 3.10)
_HAS_PROPAGATE = False
try:
    from langfuse import propagate_attributes
    _HAS_PROPAGATE = True
except ImportError:
    pass

# --- Paths ---
STATE_DIR = Path.home() / ".gemini" / "state"
LOG_FILE = STATE_DIR / "langfuse_hook.log"
STATE_FILE = STATE_DIR / "langfuse_state.json"
LOCK_FILE = STATE_DIR / "langfuse_state.lock"

DEBUG = os.environ.get("GC_LANGFUSE_DEBUG", "").lower() == "true"
MAX_CHARS = int(os.environ.get("GC_LANGFUSE_MAX_CHARS", "20000"))

# ----------------- Logging -----------------
def _log(level: str, message: str) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{ts} [{level}] {message}\n")
    except Exception:
        pass

def debug(msg: str) -> None:
    if DEBUG:
        _log("DEBUG", msg)

def info(msg: str) -> None:
    _log("INFO", msg)

def warn(msg: str) -> None:
    _log("WARN", msg)

def error(msg: str) -> None:
    _log("ERROR", msg)

# ----------------- State locking (best-effort, cross-platform) -----------------
_IS_WIN = sys.platform == "win32"

class FileLock:
    def __init__(self, path: Path, timeout_s: float = 2.0):
        self.path = path
        self.timeout_s = timeout_s
        self._fh = None

    def __enter__(self):
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "a+", encoding="utf-8")
        deadline = time.time() + self.timeout_s
        if _IS_WIN:
            try:
                import msvcrt
                while True:
                    try:
                        msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except (OSError, IOError):
                        if time.time() > deadline:
                            break
                        time.sleep(0.05)
            except Exception:
                pass
        else:
            try:
                import fcntl
                while True:
                    try:
                        fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if time.time() > deadline:
                            break
                        time.sleep(0.05)
            except Exception:
                pass
        return self

    def __exit__(self, exc_type, exc, tb):
        if _IS_WIN:
            try:
                import msvcrt
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            except Exception:
                pass
        else:
            try:
                import fcntl
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
        try:
            self._fh.close()
        except Exception:
            pass

# ----------------- State management -----------------
def load_state() -> Dict[str, Any]:
    try:
        if not STATE_FILE.exists():
            return {}
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}

def save_state(state: Dict[str, Any]) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, STATE_FILE)
    except Exception as e:
        debug(f"save_state failed: {e}")

def state_key(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]

# ----------------- Buffer management -----------------
def buffer_path(session_hash: str) -> Path:
    return STATE_DIR / f"langfuse_buffer_{session_hash}.jsonl"

def append_to_buffer(session_hash: str, event_name: str, timestamp: str, data: Dict[str, Any]) -> None:
    """Append an event to the session buffer file."""
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        bp = buffer_path(session_hash)
        entry = {"event": event_name, "timestamp": timestamp, "data": data}
        with open(bp, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        debug(f"append_to_buffer failed: {e}")

def read_and_clear_buffer(session_hash: str) -> List[Dict[str, Any]]:
    """Read all buffered events and clear the file."""
    bp = buffer_path(session_hash)
    events: List[Dict[str, Any]] = []
    try:
        if not bp.exists():
            return events
        with open(bp, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except Exception:
                    continue
        # Clear
        bp.write_text("", encoding="utf-8")
    except Exception as e:
        debug(f"read_and_clear_buffer failed: {e}")
    return events

def clear_buffer(session_hash: str) -> None:
    """Remove the buffer file."""
    try:
        bp = buffer_path(session_hash)
        if bp.exists():
            bp.unlink()
    except Exception:
        pass

# ----------------- Hook payload -----------------
def read_hook_payload() -> Dict[str, Any]:
    try:
        data = sys.stdin.read()
        if not data.strip():
            return {}
        return json.loads(data)
    except Exception:
        return {}

def output_allow() -> None:
    """Output allow decision so Gemini CLI continues normally."""
    try:
        print(json.dumps({"decision": "allow"}))
    except Exception:
        pass

@dataclass
class SessionContext:
    session_id: Optional[str] = None
    transcript_path: Optional[str] = None
    cwd: Optional[str] = None
    hook_event_name: Optional[str] = None
    timestamp: Optional[str] = None

def extract_session_context(payload: Dict[str, Any]) -> SessionContext:
    return SessionContext(
        session_id=payload.get("session_id"),
        transcript_path=payload.get("transcript_path"),
        cwd=payload.get("cwd"),
        hook_event_name=payload.get("hook_event_name"),
        timestamp=payload.get("timestamp"),
    )

# ----------------- Text helpers -----------------
def truncate_text(s: str, max_chars: int = MAX_CHARS) -> Tuple[str, Dict[str, Any]]:
    if s is None:
        return "", {"truncated": False, "orig_len": 0}
    orig_len = len(s)
    if orig_len <= max_chars:
        return s, {"truncated": False, "orig_len": orig_len}
    head = s[:max_chars]
    return head, {"truncated": True, "orig_len": orig_len, "kept_len": len(head), "sha256": hashlib.sha256(s.encode("utf-8")).hexdigest()}

def safe_str(val: Any, max_chars: int = MAX_CHARS) -> Tuple[str, Dict[str, Any]]:
    """Convert any value to a truncated string representation."""
    if val is None:
        return "", {"truncated": False, "orig_len": 0}
    if isinstance(val, str):
        return truncate_text(val, max_chars)
    try:
        s = json.dumps(val, ensure_ascii=False, default=str)
    except Exception:
        s = str(val)
    return truncate_text(s, max_chars)

# ----------------- Langfuse client factory -----------------
def create_langfuse() -> Optional[Langfuse]:
    public_key = os.environ.get("GC_LANGFUSE_PUBLIC_KEY") or os.environ.get("LANGFUSE_PUBLIC_KEY")
    secret_key = os.environ.get("GC_LANGFUSE_SECRET_KEY") or os.environ.get("LANGFUSE_SECRET_KEY")
    host = os.environ.get("GC_LANGFUSE_BASE_URL") or os.environ.get("LANGFUSE_BASE_URL") or "https://cloud.langfuse.com"

    if not public_key or not secret_key:
        return None

    try:
        return Langfuse(public_key=public_key, secret_key=secret_key, host=host)
    except Exception:
        return None

def get_user_id() -> str:
    return os.environ.get("GC_LANGFUSE_USER_ID") or os.environ.get("LANGFUSE_USER_ID") or "gemini-user"

def get_hostname() -> str:
    return os.environ.get("GC_LANGFUSE_HOSTNAME") or socket.gethostname()

# ----------------- Trace assembly from buffer -----------------
@dataclass
class TraceData:
    """Assembled trace data from buffer events."""
    prompt: str = ""
    prompt_response: str = ""
    before_agent: Optional[Dict[str, Any]] = None
    model_calls: List[Dict[str, Any]] = field(default_factory=list)
    tool_selections: List[Dict[str, Any]] = field(default_factory=list)
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    events: List[Dict[str, Any]] = field(default_factory=list)

def build_trace_from_buffer(buffer_events: List[Dict[str, Any]], payload: Dict[str, Any]) -> TraceData:
    """Assemble buffer events into structured trace data."""
    td = TraceData()
    td.prompt = payload.get("prompt", "")
    td.prompt_response = payload.get("prompt_response", "")

    # Pair BeforeTool/AfterTool by matching tool_name + sequential order
    before_tools: List[Dict[str, Any]] = []

    for ev in buffer_events:
        event_name = ev.get("event", "")
        data = ev.get("data", {})
        ts = ev.get("timestamp", "")

        if event_name == "BeforeAgent":
            td.before_agent = {"timestamp": ts, **data}

        elif event_name == "BeforeModel":
            td.model_calls.append({"phase": "before", "timestamp": ts, **data})

        elif event_name == "AfterModel":
            # Try to pair with the most recent BeforeModel
            paired = False
            for mc in reversed(td.model_calls):
                if mc.get("phase") == "before" and "after_timestamp" not in mc:
                    mc["phase"] = "paired"
                    mc["after_timestamp"] = ts
                    mc["llm_response"] = data.get("llm_response")
                    if "llm_request" not in mc and "llm_request" in data:
                        mc["llm_request"] = data["llm_request"]
                    paired = True
                    break
            if not paired:
                td.model_calls.append({"phase": "after_only", "timestamp": ts, **data})

        elif event_name == "BeforeToolSelection":
            td.tool_selections.append({"timestamp": ts, **data})

        elif event_name == "BeforeTool":
            before_tools.append({"timestamp": ts, **data})

        elif event_name == "AfterTool":
            tool_entry: Dict[str, Any] = {"timestamp": ts, **data}
            # Pair with matching BeforeTool
            for bt in reversed(before_tools):
                if bt.get("tool_name") == data.get("tool_name") and "paired" not in bt:
                    bt["paired"] = True
                    tool_entry["before_timestamp"] = bt["timestamp"]
                    tool_entry["before_input"] = bt.get("tool_input")
                    break
            td.tool_calls.append(tool_entry)

        else:
            td.events.append({"event": event_name, "timestamp": ts, **data})

    # Add unpaired BeforeTools as standalone entries
    for bt in before_tools:
        if "paired" not in bt:
            td.tool_calls.append({
                "tool_name": bt.get("tool_name", "unknown"),
                "tool_input": bt.get("tool_input"),
                "timestamp": bt["timestamp"],
                "unpaired_before": True,
            })

    return td

# ----------------- Extract usage from Gemini response -----------------
def extract_gemini_usage(llm_response: Any) -> Optional[Dict[str, int]]:
    """Extract token usage from Gemini API response."""
    if not isinstance(llm_response, dict):
        return None
    usage = llm_response.get("usageMetadata")
    if not isinstance(usage, dict):
        return None
    result: Dict[str, int] = {}
    prompt_tokens = usage.get("promptTokenCount", 0)
    candidates_tokens = usage.get("candidatesTokenCount", 0)
    total_tokens = usage.get("totalTokenCount", 0)
    if prompt_tokens:
        result["input"] = prompt_tokens
    if candidates_tokens:
        result["output"] = candidates_tokens
    if total_tokens:
        result["total"] = total_tokens
    elif prompt_tokens or candidates_tokens:
        result["total"] = prompt_tokens + candidates_tokens
    # Cache tokens
    cached = usage.get("cachedContentTokenCount", 0)
    if cached:
        result["input_cache_read"] = cached
    return result if result else None

def extract_gemini_model(llm_request: Any) -> str:
    """Extract model name from Gemini API request."""
    if isinstance(llm_request, dict):
        model = llm_request.get("model") or llm_request.get("model_name")
        if model:
            return str(model)
    return "gemini"

def extract_gemini_response_text(llm_response: Any) -> str:
    """Extract text content from Gemini API response."""
    if not isinstance(llm_response, dict):
        return ""
    candidates = llm_response.get("candidates", [])
    parts: List[str] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("content", {})
        if not isinstance(content, dict):
            continue
        for part in content.get("parts", []):
            if isinstance(part, dict) and "text" in part:
                parts.append(part["text"])
    return "\n".join(parts)

# ----------------- Langfuse emit functions -----------------
def emit_turn_trace(
    langfuse: Langfuse,
    session_id: str,
    turn_num: int,
    trace_data: TraceData,
    ctx: SessionContext,
    hostname: str,
) -> None:
    """Emit a complete turn trace to Langfuse."""
    user_id = get_user_id()
    prompt_text, prompt_meta = safe_str(trace_data.prompt)
    response_text, response_meta = safe_str(trace_data.prompt_response)

    trace_meta: Dict[str, Any] = {
        "source": "gemini-cli",
        "session_id": session_id,
        "turn_number": turn_num,
        "cwd": ctx.cwd,
        "hostname": hostname,
        "model_calls": len(trace_data.model_calls),
        "tool_calls": len(trace_data.tool_calls),
        "tool_selections": len(trace_data.tool_selections),
        "prompt_meta": prompt_meta,
        "response_meta": response_meta,
    }

    if _HAS_PROPAGATE:
        _emit_turn_modern(langfuse, session_id, user_id, turn_num, prompt_text, response_text, trace_data, trace_meta, hostname)
    else:
        _emit_turn_legacy(langfuse, session_id, user_id, turn_num, prompt_text, response_text, trace_data, trace_meta, hostname)


def _emit_turn_modern(
    langfuse, session_id, user_id, turn_num,
    prompt_text, response_text, trace_data, trace_meta, hostname,
):
    """langfuse >= 3.12: propagate_attributes + nested spans."""
    with propagate_attributes(
        session_id=session_id,
        user_id=user_id,
        trace_name=f"Gemini CLI - Turn {turn_num}",
        tags=["gemini-cli", hostname],
    ):
        step = timedelta(milliseconds=1)
        t0 = datetime.now(timezone.utc)

        with langfuse.start_as_current_span(
            name=f"Gemini CLI - Turn {turn_num}",
            input={"role": "user", "content": prompt_text},
            metadata=trace_meta,
        ) as trace_span:
            trace_span.update(start_time=t0)
            t_cursor = t0 + step

            # Agent Request span (BeforeAgent)
            if trace_data.before_agent:
                time.sleep(0.002)
                agent_input, _ = safe_str(trace_data.before_agent.get("prompt", ""))
                with langfuse.start_as_current_span(
                    name="Agent Request",
                    input={"role": "user", "content": agent_input},
                    metadata={"event": "BeforeAgent", "timestamp": trace_data.before_agent.get("timestamp")},
                ) as span:
                    span.update(start_time=t_cursor)
                t_cursor += step

            # Model calls (Generation observations)
            for i, mc in enumerate(trace_data.model_calls):
                time.sleep(0.002)
                model_name = extract_gemini_model(mc.get("llm_request"))
                llm_response = mc.get("llm_response")
                usage = extract_gemini_usage(llm_response)

                req_str, req_meta = safe_str(mc.get("llm_request"))
                resp_text = extract_gemini_response_text(llm_response)
                resp_str, resp_meta = safe_str(resp_text) if resp_text else safe_str(llm_response)

                gen_meta: Dict[str, Any] = {
                    "phase": mc.get("phase", "unknown"),
                    "request_meta": req_meta,
                    "response_meta": resp_meta,
                }

                with langfuse.start_as_current_observation(
                    name=f"LLM Call [{i + 1}]",
                    as_type="generation",
                    model=model_name,
                    input={"role": "user", "content": req_str},
                    output={"role": "assistant", "content": resp_str},
                    metadata=gen_meta,
                ) as gen_obs:
                    gen_obs.update(start_time=t_cursor)
                    if usage:
                        gen_obs.update(usage=usage)
                t_cursor += step

            # Tool selections
            for i, ts_data in enumerate(trace_data.tool_selections):
                time.sleep(0.002)
                ts_str, ts_meta = safe_str(ts_data.get("llm_request"))
                with langfuse.start_as_current_span(
                    name=f"Tool Selection [{i + 1}]",
                    input={"request": ts_str},
                    metadata={"event": "BeforeToolSelection", "timestamp": ts_data.get("timestamp"), "input_meta": ts_meta},
                ) as span:
                    span.update(start_time=t_cursor)
                t_cursor += step

            # Tool calls
            for i, tc in enumerate(trace_data.tool_calls):
                time.sleep(0.002)
                tool_name = tc.get("tool_name", "unknown")
                tool_input = tc.get("tool_input") or tc.get("before_input")
                tool_response = tc.get("tool_response")

                in_str, in_meta = safe_str(tool_input)
                out_str, out_meta = safe_str(tool_response)

                tool_meta: Dict[str, Any] = {
                    "tool_name": tool_name,
                    "input_meta": in_meta,
                    "output_meta": out_meta,
                    "before_timestamp": tc.get("before_timestamp"),
                    "after_timestamp": tc.get("timestamp"),
                }
                if tc.get("unpaired_before"):
                    tool_meta["unpaired"] = True

                with langfuse.start_as_current_observation(
                    name=f"Tool: {tool_name}",
                    as_type="tool",
                    input=tool_input if isinstance(tool_input, dict) else in_str,
                    metadata=tool_meta,
                ) as tool_obs:
                    tool_obs.update(start_time=t_cursor, output=out_str)
                t_cursor += step

            # Agent Response
            time.sleep(0.002)
            with langfuse.start_as_current_span(
                name="Agent Response",
                output={"role": "assistant", "content": response_text},
                metadata={"event": "AfterAgent"},
            ) as span:
                span.update(start_time=t_cursor)

            trace_span.update(output={"role": "assistant", "content": response_text})


def _emit_turn_legacy(
    langfuse, session_id, user_id, turn_num,
    prompt_text, response_text, trace_data, trace_meta, hostname,
):
    """langfuse >= 3.x without propagate_attributes."""
    step = timedelta(milliseconds=1)
    t0 = datetime.now(timezone.utc)

    with langfuse.start_as_current_span(
        name=f"Gemini CLI - Turn {turn_num}",
        input={"role": "user", "content": prompt_text},
        metadata=trace_meta,
    ) as trace_span:
        trace_span.update(start_time=t0)

        langfuse.update_current_trace(
            name=f"Gemini CLI - Turn {turn_num}",
            session_id=session_id,
            user_id=user_id,
            tags=["gemini-cli", hostname],
            input={"role": "user", "content": prompt_text},
            output={"role": "assistant", "content": response_text},
            metadata=trace_meta,
        )

        t_cursor = t0 + step

        # Agent Request span
        if trace_data.before_agent:
            time.sleep(0.002)
            agent_input, _ = safe_str(trace_data.before_agent.get("prompt", ""))
            with langfuse.start_as_current_span(
                name="Agent Request",
                input={"role": "user", "content": agent_input},
                metadata={"event": "BeforeAgent", "timestamp": trace_data.before_agent.get("timestamp")},
            ) as span:
                span.update(start_time=t_cursor)
            t_cursor += step

        # Model calls
        for i, mc in enumerate(trace_data.model_calls):
            time.sleep(0.002)
            model_name = extract_gemini_model(mc.get("llm_request"))
            llm_response = mc.get("llm_response")
            usage = extract_gemini_usage(llm_response)

            req_str, req_meta = safe_str(mc.get("llm_request"))
            resp_text_mc = extract_gemini_response_text(llm_response)
            resp_str, resp_meta = safe_str(resp_text_mc) if resp_text_mc else safe_str(llm_response)

            gen_meta: Dict[str, Any] = {
                "phase": mc.get("phase", "unknown"),
                "request_meta": req_meta,
                "response_meta": resp_meta,
            }

            with langfuse.start_as_current_observation(
                name=f"LLM Call [{i + 1}]",
                as_type="generation",
                model=model_name,
                input={"role": "user", "content": req_str},
                output={"role": "assistant", "content": resp_str},
                metadata=gen_meta,
            ) as gen_obs:
                gen_obs.update(start_time=t_cursor)
                if usage:
                    gen_obs.update(usage_details=usage)
            t_cursor += step

        # Tool selections
        for i, ts_data in enumerate(trace_data.tool_selections):
            time.sleep(0.002)
            ts_str, ts_meta = safe_str(ts_data.get("llm_request"))
            with langfuse.start_as_current_span(
                name=f"Tool Selection [{i + 1}]",
                input={"request": ts_str},
                metadata={"event": "BeforeToolSelection", "timestamp": ts_data.get("timestamp"), "input_meta": ts_meta},
            ) as span:
                span.update(start_time=t_cursor)
            t_cursor += step

        # Tool calls
        for i, tc in enumerate(trace_data.tool_calls):
            time.sleep(0.002)
            tool_name = tc.get("tool_name", "unknown")
            tool_input = tc.get("tool_input") or tc.get("before_input")
            tool_response = tc.get("tool_response")

            in_str, in_meta = safe_str(tool_input)
            out_str, out_meta = safe_str(tool_response)

            tool_meta: Dict[str, Any] = {
                "tool_name": tool_name,
                "input_meta": in_meta,
                "output_meta": out_meta,
                "before_timestamp": tc.get("before_timestamp"),
                "after_timestamp": tc.get("timestamp"),
            }

            with langfuse.start_as_current_observation(
                name=f"Tool: {tool_name}",
                as_type="tool",
                input=tool_input if isinstance(tool_input, dict) else in_str,
                metadata=tool_meta,
            ) as tool_obs:
                tool_obs.update(start_time=t_cursor, output=out_str)
            t_cursor += step

        # Agent Response
        time.sleep(0.002)
        with langfuse.start_as_current_span(
            name="Agent Response",
            output={"role": "assistant", "content": response_text},
            metadata={"event": "AfterAgent"},
        ) as span:
            span.update(start_time=t_cursor)

        trace_span.update(output={"role": "assistant", "content": response_text})


def emit_event(
    langfuse: Langfuse,
    session_id: str,
    event_name: str,
    data: Dict[str, Any],
    ctx: SessionContext,
    hostname: str,
) -> None:
    """Emit an independent event (SessionStart, SessionEnd, Notification, PreCompress)."""
    user_id = get_user_id()
    data_str, data_meta = safe_str(data)

    meta: Dict[str, Any] = {
        "source": "gemini-cli",
        "session_id": session_id,
        "event": event_name,
        "cwd": ctx.cwd,
        "hostname": hostname,
        "timestamp": ctx.timestamp,
        "data_meta": data_meta,
    }

    if _HAS_PROPAGATE:
        with propagate_attributes(
            session_id=session_id,
            user_id=user_id,
            trace_name=f"Gemini CLI - {event_name}",
            tags=["gemini-cli", event_name.lower(), hostname],
        ):
            with langfuse.start_as_current_span(
                name=f"Gemini CLI - {event_name}",
                input={"event": event_name},
                metadata=meta,
            ) as span:
                span.update(output={"event": event_name, "data": data_str})
    else:
        with langfuse.start_as_current_span(
            name=f"Gemini CLI - {event_name}",
            input={"event": event_name},
            metadata=meta,
        ) as span:
            langfuse.update_current_trace(
                name=f"Gemini CLI - {event_name}",
                session_id=session_id,
                user_id=user_id,
                tags=["gemini-cli", event_name.lower(), hostname],
            )
            span.update(output={"event": event_name, "data": data_str})

# ----------------- Event handlers -----------------

# Events that are buffered for AfterAgent assembly
BUFFER_EVENTS = {"BeforeAgent", "BeforeModel", "AfterModel", "BeforeToolSelection", "BeforeTool", "AfterTool"}

def handle_buffer_event(payload: Dict[str, Any], session_hash: str) -> int:
    """Buffer Before*/After* events for later assembly."""
    event = payload.get("hook_event_name", "")
    timestamp = payload.get("timestamp", datetime.now(timezone.utc).isoformat())

    # Extract event-specific data
    data: Dict[str, Any] = {}
    if event == "BeforeAgent":
        data["prompt"] = payload.get("prompt")
    elif event in ("BeforeModel", "BeforeToolSelection"):
        data["llm_request"] = payload.get("llm_request")
    elif event == "AfterModel":
        data["llm_request"] = payload.get("llm_request")
        data["llm_response"] = payload.get("llm_response")
    elif event == "BeforeTool":
        data["tool_name"] = payload.get("tool_name")
        data["tool_input"] = payload.get("tool_input")
        data["mcp_context"] = payload.get("mcp_context")
    elif event == "AfterTool":
        data["tool_name"] = payload.get("tool_name")
        data["tool_input"] = payload.get("tool_input")
        data["tool_response"] = payload.get("tool_response")
        data["mcp_context"] = payload.get("mcp_context")

    append_to_buffer(session_hash, event, timestamp, data)
    debug(f"Buffered {event} for session {session_hash}")
    return 0

def handle_after_agent(payload: Dict[str, Any], session_hash: str, langfuse: Langfuse, ctx: SessionContext, hostname: str) -> int:
    """Read buffer, assemble trace, emit to Langfuse, clear buffer."""
    session_id = ctx.session_id or "unknown"

    with FileLock(LOCK_FILE):
        state = load_state()
        key = state_key(session_id)

        # Get turn count
        session_state = state.get(key, {})
        turn_count = int(session_state.get("turn_count", 0))

        # Read buffer
        buffer_events = read_and_clear_buffer(session_hash)

        # Build trace
        trace_data = build_trace_from_buffer(buffer_events, payload)
        turn_num = turn_count + 1

        # Emit
        try:
            emit_turn_trace(langfuse, session_id, turn_num, trace_data, ctx, hostname)
        except Exception as e:
            debug(f"emit_turn_trace failed: {e}")

        # Update state
        session_state["turn_count"] = turn_num
        session_state["updated"] = datetime.now(timezone.utc).isoformat()
        state[key] = session_state
        save_state(state)

    return 0

def handle_session_start(payload: Dict[str, Any], langfuse: Langfuse, ctx: SessionContext, hostname: str) -> int:
    """Emit session start event."""
    session_id = ctx.session_id or "unknown"
    data = {"source": payload.get("source", "unknown")}
    try:
        emit_event(langfuse, session_id, "SessionStart", data, ctx, hostname)
    except Exception as e:
        debug(f"handle_session_start failed: {e}")
    return 0

def handle_session_end(payload: Dict[str, Any], session_hash: str, langfuse: Langfuse, ctx: SessionContext, hostname: str) -> int:
    """Flush remaining buffer and emit session end event."""
    session_id = ctx.session_id or "unknown"

    # Flush any remaining buffer
    with FileLock(LOCK_FILE):
        buffer_events = read_and_clear_buffer(session_hash)
        if buffer_events:
            state = load_state()
            key = state_key(session_id)
            session_state = state.get(key, {})
            turn_count = int(session_state.get("turn_count", 0))

            trace_data = build_trace_from_buffer(buffer_events, payload)
            turn_num = turn_count + 1

            try:
                emit_turn_trace(langfuse, session_id, turn_num, trace_data, ctx, hostname)
            except Exception as e:
                debug(f"SessionEnd flush failed: {e}")

            session_state["turn_count"] = turn_num
            session_state["updated"] = datetime.now(timezone.utc).isoformat()
            state[key] = session_state
            save_state(state)

    # Emit session end event
    data = {"reason": payload.get("reason", "unknown")}
    try:
        emit_event(langfuse, session_id, "SessionEnd", data, ctx, hostname)
    except Exception as e:
        debug(f"handle_session_end failed: {e}")

    # Cleanup buffer file
    clear_buffer(session_hash)
    return 0

def handle_notification(payload: Dict[str, Any], langfuse: Langfuse, ctx: SessionContext, hostname: str) -> int:
    """Emit notification as independent event."""
    session_id = ctx.session_id or "unknown"
    data = {
        "notification_type": payload.get("notification_type"),
        "message": payload.get("message"),
        "details": payload.get("details"),
    }
    try:
        emit_event(langfuse, session_id, "Notification", data, ctx, hostname)
    except Exception as e:
        debug(f"handle_notification failed: {e}")
    return 0

def handle_precompress(payload: Dict[str, Any], langfuse: Langfuse, ctx: SessionContext, hostname: str) -> int:
    """Emit context compression event."""
    session_id = ctx.session_id or "unknown"
    data = {"trigger": payload.get("trigger", "unknown")}
    try:
        emit_event(langfuse, session_id, "PreCompress", data, ctx, hostname)
    except Exception as e:
        debug(f"handle_precompress failed: {e}")
    return 0

# ----------------- Main -----------------
def main() -> int:
    start = time.time()
    debug("Hook started")

    # Always output allow so Gemini CLI continues
    output_allow()

    if os.environ.get("TRACE_TO_LANGFUSE", "").lower() != "true":
        return 0

    payload = read_hook_payload()
    if not payload:
        debug("Empty payload; exiting.")
        return 0

    ctx = extract_session_context(payload)
    event = ctx.hook_event_name or ""
    session_id = ctx.session_id or ""

    if not session_id:
        debug("Missing session_id; exiting.")
        return 0

    session_hash = state_key(session_id)
    hostname = get_hostname()

    # Buffer events don't need Langfuse client
    if event in BUFFER_EVENTS:
        return handle_buffer_event(payload, session_hash)

    # All other events need Langfuse
    langfuse = create_langfuse()
    if not langfuse:
        return 0

    try:
        if event == "AfterAgent":
            handle_after_agent(payload, session_hash, langfuse, ctx, hostname)
        elif event == "SessionStart":
            handle_session_start(payload, langfuse, ctx, hostname)
        elif event == "SessionEnd":
            handle_session_end(payload, session_hash, langfuse, ctx, hostname)
        elif event == "Notification":
            handle_notification(payload, langfuse, ctx, hostname)
        elif event == "PreCompress":
            handle_precompress(payload, langfuse, ctx, hostname)
        else:
            debug(f"Unknown event: {event}")

        try:
            langfuse.flush()
        except Exception:
            pass

        dur = time.time() - start
        info(f"Processed {event} in {dur:.2f}s (session={session_id})")

    except Exception as e:
        debug(f"Unexpected failure: {e}")

    finally:
        try:
            langfuse.shutdown()
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
