"""对话流发现模块 (session_discoverer)

负责发现系统中所有活跃的 AI CLI 对话流。扫描 Claude Code (~/.claude/projects/)
和 Codex (~/.codex/sessions/) 的 JSONL 会话文件，根据文件修改时间筛选出
10 分钟内活跃的会话，并结合 ~/.claude/sessions/<PID>.json 中的进程存活信息
确定每个工作目录下应保留的会话数量。

本模块定义了 Session 数据类（承载单个对话流的全部状态字段）和 SessionDiscoverer
服务类（执行发现逻辑），是整个流水线的第一步。
"""

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
        self.task_summary = ""         # 当前任务的高层描述（来自用户最近一条消息）
        self.ai_task_description = ""  # AI 生成的视角转换描述（覆盖模板）


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

    def _count_active_cc_instances(self):
        """读取 ~/.claude/sessions/<PID>.json 统计活跃 CC 实例数。
        返回 {cwd: count}，只计入 PID 仍存活的实例。"""
        sessions_dir = os.path.join(self.home, ".claude", "sessions")
        counts = {}
        if not os.path.isdir(sessions_dir):
            return counts
        try:
            for fname in os.listdir(sessions_dir):
                if not fname.endswith(".json"):
                    continue
                pid_str = fname[:-5]
                # 检查 PID 是否存活
                try:
                    os.kill(int(pid_str), 0)
                except (OSError, ValueError):
                    continue
                # 读取 cwd
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
        """扫描 ~/.claude/projects/ 下的活跃 JSONL。"""
        if not os.path.isdir(self.claude_base):
            return []

        # 统计每个 cwd 有几个活跃 CC 实例
        instance_counts = self._count_active_cc_instances()

        # 按 encoded_cwd 目录收集候选，按 mtime 降序取前 N 个
        # 有活跃进程的 cwd 不过滤 mtime（终端开着就一直显示）；
        # 无活跃进程的才按 ACTIVE_THRESHOLD 清理
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
                    # 进程还活着（终端开着），取最新的 N 个，不管 mtime
                    n = instance_counts[real_workspace]
                    for _, fpath, workspace, session_id in candidates[:n]:
                        sessions.append(Session(fpath, "claude", workspace, session_id))
                else:
                    # 进程已退出，仅保留近期文件用于短暂展示
                    for mtime, fpath, workspace, session_id in candidates[:1]:
                        if now - mtime <= self.ACTIVE_THRESHOLD:
                            sessions.append(Session(fpath, "claude", workspace, session_id))
        except OSError:
            pass
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
