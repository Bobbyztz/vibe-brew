"""vibe-brew：AI 编程等待期助手。主循环 + TUI 渲染。"""

import os
import signal
import sys
import time

# src/ 不是 package，确保同目录 import 可用
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from session_discoverer import SessionDiscoverer
from content_reader import ContentReader
from state_detector import StateDetector, Changes
from advisor import Advisor


class Renderer:
    """终端 TUI 渲染器，使用 alternate screen buffer。"""

    def __init__(self):
        self._in_alt_screen = False

    def enter(self):
        """进入 alternate screen buffer。"""
        sys.stdout.write("\033[?1049h")  # 进入
        sys.stdout.write("\033[?25l")    # 隐藏光标
        sys.stdout.flush()
        self._in_alt_screen = True

    def leave(self):
        """退出 alternate screen buffer，恢复终端。"""
        if self._in_alt_screen:
            sys.stdout.write("\033[?25h")    # 显示光标
            sys.stdout.write("\033[?1049l")  # 退出
            sys.stdout.flush()
            self._in_alt_screen = False

    def render(self, sessions, advice):
        """渲染一帧 TUI。"""
        try:
            cols = os.get_terminal_size().columns
        except OSError:
            cols = 80
        cols = max(cols, 40)

        lines = []

        # 标题栏
        title = " vibe-brew "
        pad = cols - len(title) - 2
        left_pad = pad // 2
        right_pad = pad - left_pad
        lines.append("╔" + "═" * left_pad + title + "═" * right_pad + "╗")
        lines.append("║" + " " * (cols - 2) + "║")

        if not sessions:
            msg = "暂无活跃对话"
            msg_pad = cols - 2 - self._display_width(msg)
            lines.append("║ " + msg + " " * max(msg_pad - 1, 0) + "║")
        else:
            for s in sessions:
                # 状态图标
                if s.has_error:
                    icon = "⚠"
                elif s.is_completed:
                    icon = "●"
                else:
                    icon = "⟳"

                cli_name = "Claude Code" if s.cli_type == "claude" else "Codex"
                ws_short = os.path.basename(s.workspace) if s.workspace else "?"
                wait_min = int(s.wait_seconds / 60) if s.wait_seconds else 0

                header = f" {icon} {cli_name} · {ws_short} · {wait_min}min"
                header_line = self._pad_line(header, cols)
                lines.append("║" + header_line + "║")

                # 状态详情
                action = s.current_action or "处理中"
                if s.is_completed:
                    action = "已完成"
                detail = f"   {action}"
                detail_line = self._pad_line(detail, cols)
                lines.append("║" + detail_line + "║")

        # 分隔线
        lines.append("╠" + "─" * (cols - 2) + "╣")

        # 建议区
        if advice:
            for aline in advice.split("\n"):
                content = f" {aline}"
                padded = self._pad_line(content, cols)
                lines.append("║" + padded + "║")
        else:
            hint = " 等待建议生成中..."
            lines.append("║" + self._pad_line(hint, cols) + "║")

        # 底部
        lines.append("║" + " " * (cols - 2) + "║")
        footer = " Ctrl+C 退出"
        lines.append("╚" + "═" * (cols - 2 - self._display_width(footer)) + footer + "╝")

        # 输出
        output = "\033[H"  # cursor home
        output += "\n".join(lines)
        # 清除剩余行
        try:
            rows = os.get_terminal_size().lines
        except OSError:
            rows = 24
        remaining = rows - len(lines)
        if remaining > 0:
            output += "\n" + "\033[K\n" * remaining

        sys.stdout.write(output)
        sys.stdout.flush()

    def _pad_line(self, text, cols):
        """将文本填充到 cols-2 的显示宽度。"""
        width = self._display_width(text)
        target = cols - 2
        if width < target:
            return text + " " * (target - width)
        elif width > target:
            # 截断
            return text[:target]
        return text

    def _display_width(self, text):
        """粗略计算显示宽度（CJK 字符占 2 列）。"""
        w = 0
        for ch in text:
            if ord(ch) > 0x7F:
                w += 2
            else:
                w += 1
        return w


def main():
    discoverer = SessionDiscoverer()
    reader = ContentReader()
    detector = StateDetector()
    advisor = Advisor()
    renderer = Renderer()

    # 进入 alternate screen
    renderer.enter()

    # 捕获 Ctrl+C
    def handle_sigint(_sig, _frame):
        renderer.leave()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_sigint)

    last_advice = ""
    last_api_call_time = 0
    sessions_state = {}

    try:
        while True:
            # 1. 发现活跃对话流
            sessions = discoverer.discover()

            # 2. 读取每个对话流的内容
            for session in sessions:
                reader.update(session)

            # 3. 检测状态变化
            changes = detector.detect(sessions, sessions_state)
            sessions_state = detector.snapshot(sessions)

            # 4. 决定是否需要更新建议
            now = time.time()
            need_update = (
                changes.has_significant_change()
                or (now - last_api_call_time >= 60 and sessions)
            )

            if need_update and sessions:
                force = changes.has_significant_change()
                result = advisor.generate(sessions, force=force)
                if result is not None:
                    last_advice = result
                    last_api_call_time = now

            if not sessions:
                last_advice = ""

            # 5. 渲染 TUI
            renderer.render(sessions, last_advice)

            time.sleep(5)

    except KeyboardInterrupt:
        pass
    finally:
        renderer.leave()


if __name__ == "__main__":
    main()
