"""内容读取模块 (content_reader)

负责从 JSONL 会话文件中增量读取并解析对话内容，将原始 JSON 记录转化为
Session 对象上的结构化状态字段（当前动作、涉及文件、是否报错/完成、
等待时长、最近消息、任务摘要等）。

支持 Claude Code 和 Codex 两种 JSONL 格式的解析。采用增量读取策略
（记录已读行数），避免每轮重复解析全部内容。同时提供 AppleScript / tmux
兜底方案，在 JSONL 不可用时从终端直接获取输出。
"""

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
            session.task_summary = cached.get("task_summary", "")
            session.ai_task_description = cached.get("ai_task_description", "")

        try:
            with open(fpath, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            return

        # 只消费以 \n 结尾的完整行，避免读到写入中的半行 JSON
        # 导致解析失败且 pos 推进过去，永远丢失该事件
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

        # 防御性回扫：如果仍未标记完成且无新行，检查最后几行
        # 覆盖两种情况：
        # 1. 之前丢失的 turn_duration / task_complete 事件
        # 2. 快速纯文本回复（如 "hi"）可能根本没有 turn_duration
        if not session.is_completed and not new_lines and complete > 0:
            try:
                idle_seconds = time.time() - os.path.getmtime(fpath)
            except OSError:
                idle_seconds = 0

            tail_start = max(0, complete - 5)
            for line in reversed(lines[tail_start:complete]):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    rtype = rec.get("type", "")
                    if rtype == "system" and rec.get("subtype") == "turn_duration":
                        session.is_completed = True
                        session.current_action = ""
                        break
                    if rtype == "event_msg" and rec.get("payload", {}).get("type") == "task_complete":
                        session.is_completed = True
                        session.current_action = ""
                        break
                    if rtype == "assistant" and idle_seconds > 5:
                        # 最后事件是 assistant 且文件已静默 5s+
                        # 检查是否纯文本（无 tool_use）→ 推断已完成
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
                        break  # 还在进行中
                except json.JSONDecodeError:
                    continue

        # 计算等待时长
        if session.last_user_time:
            session.wait_seconds = time.time() - session.last_user_time

        # 保存累积状态到缓存（ai_task_description 由 advisor 异步回填，
        # 需通过 sync_ai_description() 在 advisor 运行后同步回缓存）
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
        }

    def sync_ai_description(self, session):
        """将 advisor 回填的 ai_task_description 同步到缓存。

        advisor 在 reader.update() 之后运行，直接修改 session 对象。
        需要在 advisor 运行后调用此方法，否则下轮缓存恢复会覆盖新值。
        """
        cached = self._state_cache.get(session.file_path)
        if cached and session.ai_task_description:
            cached["ai_task_description"] = session.ai_task_description

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
                # 区分真正的用户消息 vs 工具执行结果
                msg_content = rec.get("message", {}).get("content", "")
                is_tool_result = False
                if isinstance(msg_content, list):
                    is_tool_result = any(
                        isinstance(item, dict) and item.get("type") == "tool_result"
                        for item in msg_content
                    )

                if not is_tool_result:
                    # 真正的用户消息，更新时间戳
                    ts = rec.get("timestamp", "")
                    session.last_user_time = self._parse_timestamp(ts)
                    # 记录上一轮是否已完成，用于判断是否开启新任务周期
                    was_completed = session.is_completed
                    session.is_completed = False
                    session.has_error = False
                    session.error_message = ""
                    # 提取用户消息文本
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
                        # 只在新任务周期开始时更新 task_summary
                        # （上一轮已完成 或 还没有 task_summary）
                        # 后续追问/讨论不覆盖最初的任务描述
                        if was_completed or not session.task_summary:
                            session.task_summary = self._make_task_summary(user_text)
                            session.ai_task_description = ""  # 新任务，清除旧 AI 描述
                else:
                    # 工具执行结果，检查错误/恢复
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
                            # 工具成功执行，清除之前的错误状态
                            session.has_error = False
                            session.error_message = ""

            elif rec_type == "assistant":
                content = rec.get("message", {}).get("content", [])
                has_tool_use = False
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
                            has_tool_use = True
                            name = item.get("name", "")
                            inp = item.get("input", {})
                            fpath_val = inp.get("file_path", "")
                            cmd = inp.get("command", "")
                            if cmd:
                                # 只取第一行，避免多行命令撑爆 TUI
                                cmd_short = cmd.split("\n")[0].strip()[:50]
                                session.current_action = f"{name}: {cmd_short}"
                            elif fpath_val:
                                session.current_action = f"{name} {os.path.basename(fpath_val)}"
                            else:
                                session.current_action = name
                            if fpath_val and fpath_val not in session.files_involved:
                                session.files_involved.append(fpath_val)
                                # 保留最近 10 个文件
                                if len(session.files_involved) > 10:
                                    session.files_involved = session.files_involved[-10:]
                    if has_tool_use:
                        # 有工具调用，说明还在工作
                        session.is_completed = False
                    # 纯文本不标记完成——依赖 turn_duration 系统事件判断真正结束

            elif rec_type == "system":
                if rec.get("subtype") == "turn_duration":
                    session.is_completed = True
                    session.current_action = ""  # 完成后清除，避免残留

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

    def _make_task_summary(self, text):
        """保留用户最近一条消息原文（截断），仅供 advisor 构建 prompt 使用。

        不做语义提炼——视角转换交给 AI CLI，规则引擎做不好这件事。
        面板显示依赖 ai_task_description，此字段仅作上下文传递。
        """
        first_line = text.split("\n")[0].strip()
        if not first_line:
            return ""
        if len(first_line) > 40:
            first_line = first_line[:40] + "…"
        return first_line

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
