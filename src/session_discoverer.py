"""对话流发现器：扫描 Claude Code / Codex 的活跃 JSONL 会话文件。"""

import os
import time
import subprocess
import json


class Session:
    """表示一个活跃的 AI CLI 对话流。"""

    def __init__(self, file_path, cli_type, workspace, session_id):
        self.file_path = file_path
        self.cli_type = cli_type      # "claude" 或 "codex"
        self.workspace = workspace    # 工作目录
        self.session_id = session_id
        # 由 ContentReader 填充
        self.current_action = ""
        self.files_involved = []
        self.has_error = False
        self.error_message = ""
        self.wait_seconds = 0
        self.is_completed = False
        self.last_user_time = None     # 最近用户消息时间戳
        self.recent_messages = []      # 最近的对话消息 [{"role": "user"/"assistant", "text": "..."}]


class SessionDiscoverer:
    """发现系统中活跃的 AI 编码对话流。"""

    ACTIVE_THRESHOLD = 600  # 10 分钟

    def __init__(self):
        self.home = os.path.expanduser("~")
        self.claude_base = os.path.join(self.home, ".claude", "projects")
        self.codex_base = os.path.join(self.home, ".codex", "sessions")

    def discover(self):
        """返回所有活跃 Session 列表。"""
        sessions = []
        sessions.extend(self._scan_claude())
        sessions.extend(self._scan_codex())
        return sessions

    def has_cli_process(self):
        """检测是否有 AI CLI 进程在运行（用于兜底判断）。"""
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

    def _scan_claude(self):
        """扫描 ~/.claude/projects/ 下的活跃 JSONL。"""
        sessions = []
        if not os.path.isdir(self.claude_base):
            return sessions

        now = time.time()
        try:
            for encoded_cwd in os.listdir(self.claude_base):
                cwd_dir = os.path.join(self.claude_base, encoded_cwd)
                if not os.path.isdir(cwd_dir):
                    continue
                # encoded-cwd 解码：前导 - 替换为 /，后续 - 也替换为 /
                workspace = encoded_cwd.replace("-", "/")
                if not workspace.startswith("/"):
                    workspace = "/" + workspace

                for fname in os.listdir(cwd_dir):
                    if not fname.endswith(".jsonl"):
                        continue
                    fpath = os.path.join(cwd_dir, fname)
                    if not os.path.isfile(fpath):
                        continue
                    mtime = os.path.getmtime(fpath)
                    if now - mtime > self.ACTIVE_THRESHOLD:
                        continue

                    session_id = fname[:-6]  # 去掉 .jsonl
                    # 尝试从 JSONL 获取真实 cwd
                    real_cwd = self._read_cwd_from_jsonl(fpath)
                    if real_cwd:
                        workspace = real_cwd

                    sessions.append(Session(fpath, "claude", workspace, session_id))
        except OSError:
            pass
        return sessions

    def _scan_codex(self):
        """扫描 ~/.codex/sessions/ 下的活跃 JSONL。"""
        sessions = []
        if not os.path.isdir(self.codex_base):
            return sessions

        now = time.time()
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
                    # 从首条 session_meta 提取 cwd
                    try:
                        with open(fpath, "r", encoding="utf-8") as f:
                            first_line = f.readline().strip()
                            if first_line:
                                rec = json.loads(first_line)
                                if rec.get("type") == "session_meta":
                                    workspace = rec.get("payload", {}).get("cwd", "")
                                    sid = rec.get("payload", {}).get("id", "")
                                    if sid:
                                        session_id = sid
                    except (json.JSONDecodeError, OSError):
                        pass

                    sessions.append(Session(fpath, "codex", workspace, session_id))
        except OSError:
            pass
        return sessions

    def _read_cwd_from_jsonl(self, fpath):
        """从 Claude Code JSONL 前几行读取 cwd 字段。"""
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
