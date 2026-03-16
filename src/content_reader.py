"""Content reader module (content_reader)

Incrementally reads and parses conversation content from JSONL session files,
converting raw JSON records into structured state fields on Session objects
(current action, involved files, error/completion status, wait duration,
recent messages, task summary, etc.).

Supports parsing both Claude Code and Codex JSONL formats. Uses incremental
reading (tracking lines read) to avoid re-parsing all content each cycle.
Also provides AppleScript / tmux fallback for when JSONL is unavailable.
"""

import json
import os
import subprocess
import time
from datetime import datetime


class ContentReader:
    """Reads session content and extracts structured state information."""

    def __init__(self):
        # file_path -> lines read so far
        self._read_positions = {}
        # file_path -> accumulated state cache
        self._state_cache = {}

    def update(self, session):
        """Read new JSONL lines for a session and update its state fields."""
        fpath = session.file_path
        pos = self._read_positions.get(fpath, 0)

        # Restore accumulated state from cache (discover() creates new Session objects each cycle)
        cached = self._state_cache.get(fpath)
        if cached:
            session.current_action = cached["current_action"]
            session.files_involved = list(cached["files_involved"])
            session.has_error = cached["has_error"]
            session.error_message = cached["error_message"]
            session.is_completed = cached["is_completed"]
            session.last_user_time = cached["last_user_time"]
            session.recent_messages = list(cached["recent_messages"])
            session.task_summary = cached.get("task_summary", "")
            session.ai_task_description = cached.get("ai_task_description", "")
            session._last_assistant_had_tool_use = cached.get("last_assistant_had_tool_use", False)

        try:
            with open(fpath, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            return

        # Only consume complete lines (ending with \n) to avoid reading
        # partially-written JSON that would cause parse failure and advance pos
        complete = len(lines)
        if lines and not lines[-1].endswith("\n"):
            complete -= 1

        new_lines = lines[pos:complete]
        self._read_positions[fpath] = complete

        if new_lines:
            if session.cli_type == "claude":
                self._parse_claude_lines(session, new_lines)
            elif session.cli_type == "codex":
                self._parse_codex_lines(session, new_lines)

        # Defensive back-scan: if still not marked completed and no new lines, check last few lines.
        # Covers two cases:
        # 1. Previously missed turn_duration / task_complete events
        # 2. Quick text-only replies (e.g. "hi") that may have no turn_duration at all
        if not session.is_completed and not new_lines and complete > 0:
            try:
                idle_seconds = time.time() - os.path.getmtime(fpath)
            except OSError:
                idle_seconds = 0

            tail_start = max(0, complete - 5)
            # First, find the most recent assistant message to check for tool_use
            recent_assistant_had_tool = False
            for line in reversed(lines[tail_start:complete]):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if rec.get("type") == "assistant":
                        content = rec.get("message", {}).get("content", [])
                        recent_assistant_had_tool = isinstance(content, list) and any(
                            isinstance(it, dict) and it.get("type") == "tool_use"
                            for it in content
                        )
                        break
                except json.JSONDecodeError:
                    continue

            for line in reversed(lines[tail_start:complete]):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    rtype = rec.get("type", "")
                    if rtype == "system" and rec.get("subtype") == "turn_duration":
                        # Only mark completed if the preceding assistant had no tool_use;
                        # otherwise this is an intermediate turn (e.g. during smooshing)
                        if not recent_assistant_had_tool:
                            session.is_completed = True
                            session.current_action = ""
                        break
                    if rtype == "event_msg" and rec.get("payload", {}).get("type") == "task_complete":
                        session.is_completed = True
                        session.current_action = ""
                        break
                    if rtype == "assistant" and idle_seconds > 5:
                        # Last event is assistant and file has been quiet 5s+
                        # Check if pure text (no tool_use) -> infer completed
                        content = rec.get("message", {}).get("content", [])
                        has_tool = isinstance(content, list) and any(
                            isinstance(it, dict) and it.get("type") == "tool_use"
                            for it in content
                        )
                        if not has_tool:
                            session.is_completed = True
                            session.current_action = ""
                        break
                    if rtype in ("user", "assistant", "event_msg"):
                        break  # still in progress
                except json.JSONDecodeError:
                    continue

        # Calculate wait duration
        if session.last_user_time:
            session.wait_seconds = time.time() - session.last_user_time

        # Save accumulated state to cache (ai_task_description is backfilled by advisor async,
        # needs sync_ai_description() call after advisor runs to update cache)
        self._state_cache[fpath] = {
            "current_action": session.current_action,
            "files_involved": list(session.files_involved),
            "has_error": session.has_error,
            "error_message": session.error_message,
            "is_completed": session.is_completed,
            "last_user_time": session.last_user_time,
            "recent_messages": list(session.recent_messages),
            "task_summary": session.task_summary,
            "ai_task_description": session.ai_task_description,
            "last_assistant_had_tool_use": getattr(session, "_last_assistant_had_tool_use", False),
        }

    def sync_ai_description(self, session):
        """Sync advisor-backfilled ai_task_description to cache.

        The advisor runs after reader.update() and directly modifies the session object.
        This must be called after advisor runs, otherwise next cycle's cache restore
        will overwrite the new value.
        """
        cached = self._state_cache.get(session.file_path)
        if cached and session.ai_task_description:
            cached["ai_task_description"] = session.ai_task_description

    def read_terminal_content(self):
        """Fallback: get terminal content via AppleScript / tmux."""
        content = self._try_applescript_terminal()
        if content:
            return content
        content = self._try_applescript_ghostty()
        if content:
            return content
        content = self._try_tmux()
        if content:
            return content
        return ""

    def _parse_claude_lines(self, session, lines):
        """Parse Claude Code JSONL lines."""
        last_had_tool = getattr(session, "_last_assistant_had_tool_use", False)
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue

            rec_type = rec.get("type", "")

            if rec_type == "user":
                # Distinguish real user messages vs tool execution results
                msg_content = rec.get("message", {}).get("content", "")
                is_tool_result = False
                if isinstance(msg_content, list):
                    is_tool_result = any(
                        isinstance(item, dict) and item.get("type") == "tool_result"
                        for item in msg_content
                    )

                if not is_tool_result:
                    # Real user message, update timestamp
                    ts = rec.get("timestamp", "")
                    session.last_user_time = self._parse_timestamp(ts)
                    # Track whether previous turn was completed, to detect new task cycle
                    was_completed = session.is_completed
                    session.is_completed = False
                    session.has_error = False
                    session.error_message = ""
                    # Extract user message text
                    user_text = ""
                    if isinstance(msg_content, str) and msg_content.strip():
                        user_text = msg_content.strip()
                    elif isinstance(msg_content, list):
                        for item in msg_content:
                            if isinstance(item, dict) and item.get("type") == "text":
                                user_text = item.get("text", "").strip()
                                break
                            elif isinstance(item, str):
                                user_text = item.strip()
                                break
                    if user_text:
                        self._add_message(session, "user", user_text[:200])
                        # Only update task_summary at the start of a new task cycle
                        # (previous turn completed or no task_summary yet)
                        # Follow-up questions don't overwrite the initial task description
                        if was_completed or not session.task_summary:
                            session.task_summary = self._make_task_summary(user_text)
                            session.ai_task_description = ""  # new task, clear old AI description
                else:
                    # Tool execution result, check for errors/recovery
                    if isinstance(msg_content, list):
                        has_err = False
                        for item in msg_content:
                            if isinstance(item, dict) and item.get("is_error"):
                                has_err = True
                                err = item.get("content", "")
                                if isinstance(err, str):
                                    session.error_message = err[:100]
                        if has_err:
                            session.has_error = True
                        elif session.has_error:
                            # Tool executed successfully, clear previous error state
                            session.has_error = False
                            session.error_message = ""

            elif rec_type == "assistant":
                content = rec.get("message", {}).get("content", [])
                has_tool_use = False
                if isinstance(content, list):
                    # Extract AI text reply
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            text = item.get("text", "").strip()
                            if text:
                                self._add_message(session, "assistant", text[:200])
                                break
                    for item in content:
                        if not isinstance(item, dict):
                            continue
                        if item.get("type") == "tool_use":
                            has_tool_use = True
                            name = item.get("name", "")
                            inp = item.get("input", {})
                            fpath_val = inp.get("file_path", "")
                            cmd = inp.get("command", "")
                            if cmd:
                                # Take only first line to avoid multi-line commands blowing up TUI
                                cmd_short = cmd.split("\n")[0].strip()[:50]
                                session.current_action = f"{name}: {cmd_short}"
                            elif fpath_val:
                                session.current_action = f"{name} {os.path.basename(fpath_val)}"
                            else:
                                session.current_action = name
                            if fpath_val and fpath_val not in session.files_involved:
                                session.files_involved.append(fpath_val)
                                # Keep only the most recent 10 files
                                if len(session.files_involved) > 10:
                                    session.files_involved = session.files_involved[-10:]
                    last_had_tool = has_tool_use
                    if has_tool_use:
                        # Has tool calls, still working
                        session.is_completed = False
                    # Pure text doesn't mark completion -- rely on turn_duration system event

            elif rec_type == "system":
                if rec.get("subtype") == "turn_duration":
                    if not last_had_tool:
                        # Final turn (pure text reply) -- mark completed
                        session.is_completed = True
                        session.current_action = ""
                    # If last assistant had tool_use, this is an intermediate turn
                    # in the agent loop (e.g. between tool call and tool result,
                    # or during smooshing) -- do NOT mark completed

        session._last_assistant_had_tool_use = last_had_tool

    def _parse_codex_lines(self, session, lines):
        """Parse Codex JSONL lines."""
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue

            rec_type = rec.get("type", "")
            payload = rec.get("payload", {})

            if rec_type == "session_meta":
                cwd = payload.get("cwd", "")
                if cwd:
                    session.workspace = cwd

            elif rec_type == "event_msg":
                ptype = payload.get("type", "")
                if ptype == "user_message":
                    ts = rec.get("timestamp", "")
                    session.last_user_time = self._parse_timestamp(ts)
                    was_completed = session.is_completed
                    session.is_completed = False
                    session.has_error = False
                    session.error_message = ""
                    text = payload.get("message", "")
                    if isinstance(text, str) and text.strip():
                        self._add_message(session, "user", text.strip()[:200])
                        if was_completed or not session.task_summary:
                            session.task_summary = self._make_task_summary(text.strip())
                            session.ai_task_description = ""
                elif ptype == "agent_message":
                    text = payload.get("message", "")
                    if isinstance(text, str) and text.strip():
                        self._add_message(session, "assistant", text.strip()[:200])
                elif ptype == "task_complete":
                    session.is_completed = True
                    session.current_action = ""

            elif rec_type == "response_item":
                ptype = payload.get("type", "")
                if ptype == "function_call":
                    name = payload.get("name", "")
                    args_str = payload.get("arguments", "")
                    session.current_action = name
                    # Try to extract file path
                    try:
                        args = json.loads(args_str)
                        cmd = args.get("cmd", "")
                        if cmd:
                            session.current_action = f"{name}: {cmd[:60]}"
                    except (json.JSONDecodeError, TypeError):
                        pass

                elif ptype == "function_call_output":
                    output = payload.get("output", "")
                    if isinstance(output, str):
                        lower = output.lower()
                        if "error" in lower or "exited with code 1" in lower:
                            session.has_error = True
                            session.error_message = output[:100]

    def _make_task_summary(self, text):
        """Keep user's latest message text (truncated), for advisor prompt construction only.

        No semantic extraction -- perspective shifting is delegated to the AI CLI.
        The rule engine can't do this well. Panel display relies on ai_task_description;
        this field is only for context passing.
        """
        first_line = text.split("\n")[0].strip()
        if not first_line:
            return ""
        if len(first_line) > 40:
            first_line = first_line[:40] + "\u2026"
        return first_line

    def _add_message(self, session, role, text):
        """Add a conversation message, keeping the latest 3 each for user and assistant."""
        session.recent_messages.append({"role": role, "text": text})
        # Keep latest 3 per role, then merge in original order
        user_msgs = [m for m in session.recent_messages if m["role"] == "user"][-3:]
        asst_msgs = [m for m in session.recent_messages if m["role"] == "assistant"][-3:]
        kept = set()
        for m in user_msgs + asst_msgs:
            kept.add(id(m))
        session.recent_messages = [m for m in session.recent_messages if id(m) in kept]

    def _parse_timestamp(self, ts):
        """Parse ISO 8601 timestamp, return epoch seconds."""
        if not ts:
            return None
        try:
            ts = ts.replace("Z", "+00:00")
            dt = datetime.fromisoformat(ts)
            return dt.timestamp()
        except (ValueError, TypeError):
            return None

    def _try_applescript_terminal(self):
        """Get Terminal.app content via AppleScript."""
        script = 'tell application "Terminal" to get contents of selected tab of front window'
        return self._run_osascript(script)

    def _try_applescript_ghostty(self):
        """Get Ghostty content via AppleScript."""
        script = 'tell application "Ghostty" to get contents of current terminal of front window'
        return self._run_osascript(script)

    def _try_tmux(self):
        """Get content via tmux capture-pane."""
        if not os.environ.get("TMUX"):
            return ""
        try:
            result = subprocess.run(
                ["tmux", "capture-pane", "-p", "-S", "-"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                return result.stdout
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return ""

    def _run_osascript(self, script):
        """Execute osascript, return output or empty string."""
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return ""
