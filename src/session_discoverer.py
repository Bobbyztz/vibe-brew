"""Session discovery module (session_discoverer)

Discovers all active AI CLI sessions on the system. Scans Claude Code
(~/.claude/projects/) and Codex (~/.codex/sessions/) JSONL session files,
filters for sessions active within the last 10 minutes by file modification time,
and uses ~/.claude/sessions/<PID>.json process liveness info to determine
how many sessions to keep per working directory.

Defines the Session data class (carrying all state fields for a single session)
and the SessionDiscoverer service class (executing discovery logic). This is the
first step in the pipeline.
"""

import os
import time
import subprocess
import json


class Session:
    """Represents an active AI CLI session."""

    def __init__(self, file_path, cli_type, workspace, session_id):
        self.file_path = file_path
        self.cli_type = cli_type      # "claude" or "codex"
        self.workspace = workspace    # working directory
        self.session_id = session_id
        # Populated by ContentReader
        self.current_action = ""
        self.files_involved = []
        self.has_error = False
        self.error_message = ""
        self.wait_seconds = 0
        self.is_completed = False
        self.last_user_time = None     # timestamp of most recent user message
        self.recent_messages = []      # recent conversation messages [{"role": "user"/"assistant", "text": "..."}]
        self.task_summary = ""         # high-level description of current task (from user's latest message)
        self.ai_task_description = ""  # AI-generated perspective-shifted description (overrides templates)
        self.has_live_process = False  # whether a live CLI process owns this session
        self.subagent_files = []      # file paths of child subagent sessions (codex)


class SessionDiscoverer:
    """Discovers active AI coding sessions on the system."""

    ACTIVE_THRESHOLD = 600  # 10 minutes

    def __init__(self):
        self.home = os.path.expanduser("~")
        self.claude_base = os.path.join(self.home, ".claude", "projects")
        self.codex_base = os.path.join(self.home, ".codex", "sessions")

    def discover(self):
        """Return a list of all active Sessions."""
        sessions = []
        sessions.extend(self._scan_claude())
        sessions.extend(self._scan_codex())
        return sessions

    def _count_active_cc_instances(self):
        """Read ~/.claude/sessions/<PID>.json to count active CC instances.
        Returns {cwd: count}, only counting PIDs that are still alive."""
        sessions_dir = os.path.join(self.home, ".claude", "sessions")
        counts = {}
        if not os.path.isdir(sessions_dir):
            return counts
        try:
            for fname in os.listdir(sessions_dir):
                if not fname.endswith(".json"):
                    continue
                pid_str = fname[:-5]
                # Check if PID is still alive
                try:
                    os.kill(int(pid_str), 0)
                except (OSError, ValueError):
                    continue
                # Read cwd
                fpath = os.path.join(sessions_dir, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        rec = json.loads(f.read())
                    cwd = rec.get("cwd", "")
                    if cwd:
                        counts[cwd] = counts.get(cwd, 0) + 1
                except (json.JSONDecodeError, OSError):
                    continue
        except OSError:
            pass
        return counts

    def _scan_claude(self):
        """Scan ~/.claude/projects/ for active JSONL files."""
        if not os.path.isdir(self.claude_base):
            return []

        # Count active CC instances per cwd
        instance_counts = self._count_active_cc_instances()

        # Collect candidates per encoded_cwd directory, sorted by mtime descending, take top N.
        # cwds with live processes skip mtime filtering (terminal is open, keep showing);
        # cwds without live processes filter by ACTIVE_THRESHOLD
        sessions = []
        now = time.time()
        try:
            for encoded_cwd in os.listdir(self.claude_base):
                cwd_dir = os.path.join(self.claude_base, encoded_cwd)
                if not os.path.isdir(cwd_dir):
                    continue
                default_workspace = encoded_cwd.replace("-", "/")
                if not default_workspace.startswith("/"):
                    default_workspace = "/" + default_workspace

                candidates = []  # [(mtime, fpath, workspace, session_id)]
                for fname in os.listdir(cwd_dir):
                    if not fname.endswith(".jsonl"):
                        continue
                    fpath = os.path.join(cwd_dir, fname)
                    if not os.path.isfile(fpath):
                        continue
                    mtime = os.path.getmtime(fpath)
                    session_id = fname[:-6]
                    workspace = default_workspace
                    real_cwd = self._read_cwd_from_jsonl(fpath)
                    if real_cwd:
                        workspace = real_cwd
                    candidates.append((mtime, fpath, workspace, session_id))

                if not candidates:
                    continue

                candidates.sort(key=lambda x: x[0], reverse=True)
                real_workspace = candidates[0][2]
                has_live_process = real_workspace in instance_counts

                if has_live_process:
                    # Process still alive (terminal open), take the latest N regardless of mtime
                    n = instance_counts[real_workspace]
                    for _, fpath, workspace, session_id in candidates[:n]:
                        s = Session(fpath, "claude", workspace, session_id)
                        s.has_live_process = True
                        sessions.append(s)
                else:
                    # Process exited, only keep recent files for brief display
                    for mtime, fpath, workspace, session_id in candidates[:1]:
                        if now - mtime <= self.ACTIVE_THRESHOLD:
                            sessions.append(Session(fpath, "claude", workspace, session_id))
        except OSError:
            pass
        return sessions

    def has_cli_process(self):
        """Check if any AI CLI process is running (used as fallback signal)."""
        for name in ("claude", "codex"):
            try:
                result = subprocess.run(
                    ["pgrep", "-f", name],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0 and result.stdout.strip():
                    return True
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass
        return False

    def _scan_codex(self):
        """Scan ~/.codex/sessions/ for active JSONL files.

        Subagent sessions (source.subagent in session_meta) are filtered out
        and their file paths attached to the parent session for completion tracking.
        """
        if not os.path.isdir(self.codex_base):
            return []

        now = time.time()
        # First pass: classify files into parents and subagents
        parents = {}      # session_id -> (fpath, workspace, mtime)
        subagents = {}    # parent_thread_id -> [fpath, ...]
        try:
            for root, _dirs, files in os.walk(self.codex_base):
                for fname in files:
                    if not fname.endswith(".jsonl"):
                        continue
                    fpath = os.path.join(root, fname)
                    mtime = os.path.getmtime(fpath)
                    if now - mtime > self.ACTIVE_THRESHOLD:
                        continue

                    session_id = fname[:-6]
                    workspace = ""
                    is_subagent = False
                    parent_id = ""
                    try:
                        with open(fpath, "r", encoding="utf-8") as f:
                            first_line = f.readline().strip()
                            if first_line:
                                rec = json.loads(first_line)
                                if rec.get("type") == "session_meta":
                                    payload = rec.get("payload", {})
                                    workspace = payload.get("cwd", "")
                                    sid = payload.get("id", "")
                                    if sid:
                                        session_id = sid
                                    source = payload.get("source", "")
                                    if isinstance(source, dict) and "subagent" in source:
                                        is_subagent = True
                                        parent_id = source["subagent"].get(
                                            "thread_spawn", {}
                                        ).get("parent_thread_id", "")
                    except (json.JSONDecodeError, OSError):
                        pass

                    if is_subagent and parent_id:
                        subagents.setdefault(parent_id, []).append(fpath)
                    else:
                        parents[session_id] = (fpath, workspace, mtime)
        except OSError:
            pass

        # Second pass: build parent Sessions with subagent file lists
        sessions = []
        for session_id, (fpath, workspace, _mtime) in parents.items():
            s = Session(fpath, "codex", workspace, session_id)
            s.subagent_files = subagents.get(session_id, [])
            sessions.append(s)
        return sessions

    def _read_cwd_from_jsonl(self, fpath):
        """Read the cwd field from the first few lines of a Claude Code JSONL file."""
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                for _ in range(20):
                    line = f.readline()
                    if not line:
                        break
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        cwd = rec.get("cwd", "")
                        if cwd:
                            return cwd
                    except json.JSONDecodeError:
                        continue
        except OSError:
            pass
        return ""
