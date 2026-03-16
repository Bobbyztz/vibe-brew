"""终端标签重命名模块 (terminal_renamer)

自动检测终端标签页的工作目录，将运行 AI CLI 的标签重命名为项目名称，
解决多个标签都显示 "claude" / "codex" 无法区分的问题。

支持：Ghostty（AppleScript API 直读 working directory，需 v1.3+）、
Terminal.app（AppleScript tty + lsof 推断工作目录）。
"""

import os
import subprocess
import time


class TerminalRenamer:
    """检测终端标签并重命名为项目名。"""

    MIN_INTERVAL = 10  # 秒

    def __init__(self):
        self._last_run = 0

    def rename(self, sessions):
        """重命名终端标签。每 MIN_INTERVAL 秒最多执行一次。"""
        now = time.time()
        if now - self._last_run < self.MIN_INTERVAL:
            return
        self._last_run = now

        if not sessions:
            return

        # workspace path -> project basename
        ws_names = {}
        for s in sessions:
            if s.workspace:
                ws_names[s.workspace] = os.path.basename(s.workspace)

        if not ws_names:
            return

        self._rename_ghostty(ws_names)
        self._rename_terminal_app(ws_names)

    def _rename_ghostty(self, ws_names):
        """Ghostty: 通过 perform action "set_tab_title:..." 钉住标签标题。

        使用 Ghostty 的 set_tab_title action（而非直接设 name 属性），
        该 action 会"钉住"标题，不会被 CLI 进程的 OSC 转义序列覆盖。
        """
        if not self._is_app_running("Ghostty"):
            return

        # 动态生成 if/else 条件：匹配 cwd 后执行 perform action
        conditions = []
        for ws, name in ws_names.items():
            safe_ws = ws.replace("\\", "\\\\").replace('"', '\\"')
            safe_name = name.replace("\\", "\\\\").replace('"', '\\"')
            conditions.append(
                f'if cwd is "{safe_ws}" then\n'
                f'                        perform action "set_tab_title:{safe_name}" on term'
            )

        if not conditions:
            return

        cond_block = "\n                    else ".join(conditions)
        cond_block += "\n                    end if"

        script = (
            'tell application "Ghostty"\n'
            "    repeat with win in windows\n"
            "        repeat with t in tabs of win\n"
            "            try\n"
            "                set tname to name of t\n"
            "                if tname contains \"Claude Code\" or tname contains \"Codex\" then\n"
            "                    set term to focused terminal of t\n"
            "                    set cwd to working directory of term\n"
            '                    if cwd is not "" then\n'
            f"                        {cond_block}\n"
            "                    end if\n"
            "                end if\n"
            "            end try\n"
            "        end repeat\n"
            "    end repeat\n"
            "end tell"
        )
        self._run_osascript(script)

    def _rename_terminal_app(self, ws_names):
        """Terminal.app: 通过 tty + lsof 推断工作目录并重命名。"""
        if not self._is_app_running("Terminal"):
            return

        # 一次性获取运行 CC/Codex 的标签的 tty（按标签名过滤）
        script = (
            'tell application "Terminal"\n'
            '    set r to ""\n'
            "    repeat with w from 1 to count of windows\n"
            "        repeat with t from 1 to count of tabs of window w\n"
            "            set tname to name of tab t of window w\n"
            '            if tname contains "claude" or tname contains "codex" then\n'
            "                set theTTY to tty of tab t of window w\n"
            '                set r to r & w & "," & t & "," & theTTY & linefeed\n'
            "            end if\n"
            "        end repeat\n"
            "    end repeat\n"
            "    return r\n"
            "end tell"
        )
        output = self._run_osascript(script)
        if not output:
            return

        for line in output.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            parts = line.split(",", 2)
            if len(parts) != 3:
                continue
            win_idx, tab_idx, tty = parts
            if not tty:
                continue

            cwd = self._get_tty_cwd(tty)
            if cwd in ws_names:
                safe_name = ws_names[cwd].replace("\\", "\\\\").replace('"', '\\"')
                self._run_osascript(
                    f'tell application "Terminal" to '
                    f"set custom title of tab {tab_idx} of window {win_idx} "
                    f'to "{safe_name}"'
                )

    def _get_tty_cwd(self, tty):
        """通过 lsof 获取 tty 上进程的工作目录。"""
        try:
            # 查找该 tty 上的进程（取最小 PID，通常是 shell）
            r = subprocess.run(
                ["lsof", "-t", tty],
                capture_output=True, text=True, timeout=3,
            )
            if r.returncode != 0 or not r.stdout.strip():
                return ""

            pid = r.stdout.strip().split("\n")[0].strip()

            # 获取该进程的工作目录
            r = subprocess.run(
                ["lsof", "-a", "-d", "cwd", "-p", pid, "-Fn"],
                capture_output=True, text=True, timeout=3,
            )
            if r.returncode != 0:
                return ""

            for ln in r.stdout.strip().split("\n"):
                if ln.startswith("n"):
                    return ln[1:]
        except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
            pass
        return ""

    def _is_app_running(self, app_name):
        """检查应用是否正在运行（不会启动它）。"""
        output = self._run_osascript(
            f'tell application "System Events" to return '
            f'(name of every process whose name is "{app_name}") as text'
        )
        return bool(output)

    def _run_osascript(self, script):
        """执行 osascript，返回输出或空字符串。"""
        try:
            r = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0:
                return r.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return ""
