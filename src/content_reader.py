"""内容读取器：从 JSONL 文件解析对话状态，兜底通过终端获取内容。"""

import json
import os
import subprocess
import time
from datetime import datetime


class ContentReader:
    """读取对话流内容，提取结构化状态信息。"""

    def __init__(self):
        # file_path -> 已读行数
        self._read_positions = {}
        # file_path -> 累积状态缓存
        self._state_cache = {}

    def update(self, session):
        """读取 session 的 JSONL 新增行，更新 session 状态字段。"""
        fpath = session.file_path
        pos = self._read_positions.get(fpath, 0)

        # 先从缓存恢复累积状态（因为 discover() 每轮创建新 Session 对象）
        cached = self._state_cache.get(fpath)
        if cached:
            session.current_action = cached["current_action"]
            session.files_involved = list(cached["files_involved"])
            session.has_error = cached["has_error"]
            session.error_message = cached["error_message"]
            session.is_completed = cached["is_completed"]
            session.last_user_time = cached["last_user_time"]
            session.recent_messages = list(cached["recent_messages"])

        try:
            with open(fpath, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            return

        new_lines = lines[pos:]
        self._read_positions[fpath] = len(lines)

        if new_lines:
            if session.cli_type == "claude":
                self._parse_claude_lines(session, new_lines)
            elif session.cli_type == "codex":
                self._parse_codex_lines(session, new_lines)

        # 计算等待时长
        if session.last_user_time:
            session.wait_seconds = time.time() - session.last_user_time

        # 保存累积状态到缓存
        self._state_cache[fpath] = {
            "current_action": session.current_action,
            "files_involved": list(session.files_involved),
            "has_error": session.has_error,
            "error_message": session.error_message,
            "is_completed": session.is_completed,
            "last_user_time": session.last_user_time,
            "recent_messages": list(session.recent_messages),
        }

    def read_terminal_content(self):
        """兜底：通过 AppleScript / tmux 获取终端内容。"""
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
        """解析 Claude Code JSONL 行。"""
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
                # 工具结果 vs 用户消息
                if "toolUseResult" not in rec:
                    # 真正的用户消息，更新时间戳
                    ts = rec.get("timestamp", "")
                    session.last_user_time = self._parse_timestamp(ts)
                    session.is_completed = False
                    session.has_error = False
                    session.error_message = ""
                    # 提取用户消息文本
                    msg_content = rec.get("message", {}).get("content", "")
                    if isinstance(msg_content, str) and msg_content.strip():
                        self._add_message(session, "user", msg_content.strip()[:200])
                    elif isinstance(msg_content, list):
                        for item in msg_content:
                            if isinstance(item, dict) and item.get("type") == "text":
                                self._add_message(session, "user", item.get("text", "")[:200])
                                break
                            elif isinstance(item, str):
                                self._add_message(session, "user", item[:200])
                                break
                else:
                    # 工具执行结果，检查错误
                    content = rec.get("message", {}).get("content", [])
                    if isinstance(content, list):
                        for item in content:
                            if isinstance(item, dict) and item.get("is_error"):
                                session.has_error = True
                                err = item.get("content", "")
                                if isinstance(err, str):
                                    session.error_message = err[:100]

            elif rec_type == "assistant":
                content = rec.get("message", {}).get("content", [])
                if isinstance(content, list):
                    # 提取 AI 文本回复
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
                            name = item.get("name", "")
                            inp = item.get("input", {})
                            fpath_val = inp.get("file_path", "")
                            cmd = inp.get("command", "")
                            if cmd:
                                session.current_action = f"{name}: {cmd[:60]}"
                            elif fpath_val:
                                session.current_action = f"{name} {os.path.basename(fpath_val)}"
                            else:
                                session.current_action = name
                            if fpath_val and fpath_val not in session.files_involved:
                                session.files_involved.append(fpath_val)
                                # 保留最近 10 个文件
                                if len(session.files_involved) > 10:
                                    session.files_involved = session.files_involved[-10:]

            elif rec_type == "system":
                if rec.get("subtype") == "turn_duration":
                    session.is_completed = True

    def _parse_codex_lines(self, session, lines):
        """解析 Codex JSONL 行。"""
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
                    session.is_completed = False
                    session.has_error = False
                    session.error_message = ""
                    text = payload.get("message", "")
                    if isinstance(text, str) and text.strip():
                        self._add_message(session, "user", text.strip()[:200])
                elif ptype == "agent_message":
                    text = payload.get("message", "")
                    if isinstance(text, str) and text.strip():
                        self._add_message(session, "assistant", text.strip()[:200])
                elif ptype == "task_complete":
                    session.is_completed = True

            elif rec_type == "response_item":
                ptype = payload.get("type", "")
                if ptype == "function_call":
                    name = payload.get("name", "")
                    args_str = payload.get("arguments", "")
                    session.current_action = name
                    # 尝试提取文件路径
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

    def _add_message(self, session, role, text):
        """添加一条对话消息，保留最近的 user 和 assistant 各 3 条。"""
        session.recent_messages.append({"role": role, "text": text})
        # 分别保留各角色最近 3 条，再按原顺序合并
        user_msgs = [m for m in session.recent_messages if m["role"] == "user"][-3:]
        asst_msgs = [m for m in session.recent_messages if m["role"] == "assistant"][-3:]
        # 按在原列表中的出现顺序重建
        kept = set()
        for m in user_msgs + asst_msgs:
            kept.add(id(m))
        session.recent_messages = [m for m in session.recent_messages if id(m) in kept]

    def _parse_timestamp(self, ts):
        """解析 ISO 8601 时间戳，返回 epoch 秒。"""
        if not ts:
            return None
        try:
            # 处理带 Z 或 +00:00 的时间戳
            ts = ts.replace("Z", "+00:00")
            dt = datetime.fromisoformat(ts)
            return dt.timestamp()
        except (ValueError, TypeError):
            return None

    def _try_applescript_terminal(self):
        """通过 AppleScript 获取 Terminal.app 内容。"""
        script = 'tell application "Terminal" to get contents of selected tab of front window'
        return self._run_osascript(script)

    def _try_applescript_ghostty(self):
        """通过 AppleScript 获取 Ghostty 内容。"""
        script = 'tell application "Ghostty" to get contents of current terminal of front window'
        return self._run_osascript(script)

    def _try_tmux(self):
        """通过 tmux capture-pane 获取内容。"""
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
        """执行 osascript，返回输出或空字符串。"""
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
