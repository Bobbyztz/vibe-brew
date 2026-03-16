"""主入口模块 (vibe_brew)

vibe-brew 的唯一入口，安装后运行 `vibe-brew` 启动。包含主循环和
TUI 渲染器两部分：

主循环每 2 秒执行一轮流水线：发现活跃对话流 → 读取内容 → 检测状态变化
→ 生成建议 → 渲染 TUI。会话列表采用稳定排序（新会话追加到末尾，已有会话
保持原位），避免 TUI 闪烁。

Renderer 类使用 alternate screen buffer 实现全屏 TUI，支持 CJK 字符宽度
计算、会话状态图标（⟳/●/⚠）、建议区展示，Ctrl+C 优雅退出并恢复终端。
"""

import os
import signal
import sys
import time

from .session_discoverer import SessionDiscoverer
from .content_reader import ContentReader
from .state_detector import StateDetector, Changes
from .advisor import Advisor
from .terminal_renamer import TerminalRenamer


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
            for i, s in enumerate(sessions):
                # 状态图标（完成优先于报错，中途出错但最终跑完的算完成）
                if s.is_completed:
                    icon = "●"
                elif s.has_error:
                    icon = "⚠"
                else:
                    icon = "⟳"

                cli_name = "Claude Code" if s.cli_type == "claude" else "Codex"
                ws_short = os.path.basename(s.workspace) if s.workspace else "?"

                task = s.ai_task_description or s.task_summary or ""
                task_part = f" · {task}" if task else ""
                header = f" {icon} {cli_name} · {ws_short}{task_part}"
                header_line = self._pad_line(header, cols)
                lines.append("║" + header_line + "║")

                # 状态详情 + 时间（如 "进行中 5min"）
                detail = self._format_status(s)
                if not s.is_completed and s.wait_seconds:
                    if s.wait_seconds < 60:
                        detail += f" {int(s.wait_seconds)}s"
                    else:
                        detail += f" {int(s.wait_seconds / 60)}min"
                for dl in self._wrap_lines(f"   {detail}", cols, indent=3, max_lines=2):
                    lines.append("║" + self._pad_line(dl, cols) + "║")

                # 处理中时显示当前工具动作（如 Read main.py）
                if not s.is_completed and s.current_action:
                    action_line = self._pad_line(f"   → {s.current_action}", cols)
                    lines.append("║" + action_line + "║")

                # 会话之间加空行
                if i < len(sessions) - 1:
                    lines.append("║" + " " * (cols - 2) + "║")

        # 监控区底部空行 + 分隔线 + 建议区顶部空行
        lines.append("║" + " " * (cols - 2) + "║")
        lines.append("╠" + "─" * (cols - 2) + "╣")
        lines.append("║" + " " * (cols - 2) + "║")

        # 建议区（支持折行，每条建议后加空行增加呼吸感）
        if advice:
            advice_lines = advice.split("\n")
            for i, aline in enumerate(advice_lines):
                content = f" {aline}"
                for wl in self._wrap_lines(content, cols, indent=3, max_lines=2):
                    padded = self._pad_line(wl, cols)
                    lines.append("║" + padded + "║")
                if i < len(advice_lines) - 1:
                    lines.append("║" + " " * (cols - 2) + "║")
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

    # 出错状态模板
    _TPL_ERROR = [
        "{s}时遇到问题",
        "{s}出了点状况",
    ]

    def _format_status(self, session):
        """生成面板状态描述文本。

        监控区只显示简洁状态，任务描述已移至建议区展示。
        出错时保留详情方便快速定位。
        """
        if session.is_completed:
            return "处理完毕"
        elif session.has_error:
            desc = session.ai_task_description
            fallback = session.task_summary
            if desc:
                return self._pick_tpl(self._TPL_ERROR, session.session_id, desc)
            err = session.error_message[:20] if session.error_message else ""
            if err:
                return f"遇到了问题：{err}"
            if fallback:
                return f"处理时出错 · {fallback}"
            return "遇到了问题"
        else:
            return "进行中"

    # CJK 标点和空格，适合在其后换行
    _BREAK_AFTER = set(" \t，。；！？、）】》」』：")

    def _wrap_lines(self, text, cols, indent=3, max_lines=2):
        """按显示宽度折行，优先在空格/标点后断开。

        第二行起缩进 indent+2 格，最多 max_lines 行。
        """
        avail = cols - 2  # 两侧 ║ 占位
        if self._display_width(text) <= avail:
            return [text]

        # 逐字符扫描，记录最近可断点
        best_break = 0   # 最近可断点的字符索引（断在该字符之后）
        best_break_w = 0  # 该断点对应的显示宽度
        w = 0
        for i, ch in enumerate(text):
            cw = 2 if ord(ch) > 0x7F else 1
            w += cw
            if ch in self._BREAK_AFTER:
                best_break = i + 1
                best_break_w = w
            if w > avail:
                # 需要断行
                if best_break > 0 and best_break_w > avail * 0.4:
                    # 在可断点处断开（不能太靠前，否则第一行太短）
                    split = best_break
                else:
                    # 没有好的断点，硬切
                    split = i
                line1 = text[:split]
                prefix = " " * (indent + 2)
                line2 = prefix + text[split:].lstrip()
                return [line1, line2][:max_lines]

        return [text]

    def _pick_tpl(self, templates, session_id, summary):
        """按 session_id hash 稳定选模板，同一会话不会每帧跳动。"""
        idx = hash(session_id) % len(templates)
        return templates[idx].format(s=summary)

    def _pad_line(self, text, cols):
        """将文本填充到 cols-2 的显示宽度，保证单行安全。"""
        # 防御多行内容：只取第一行
        text = text.split("\n")[0]
        target = cols - 2
        width = self._display_width(text)
        if width < target:
            return text + " " * (target - width)
        elif width > target:
            # 按显示宽度截断（而非字符数），避免 CJK 字符被切半
            result = []
            w = 0
            for ch in text:
                cw = 2 if ord(ch) > 0x7F else 1
                if w + cw > target - 1:  # 留 1 列给 "…"
                    result.append("…")
                    break
                result.append(ch)
                w += cw
            truncated = "".join(result)
            # 补齐到 target 宽度
            pad = target - self._display_width(truncated)
            return truncated + " " * max(pad, 0)
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
    renamer = TerminalRenamer()

    # 进入 alternate screen
    renderer.enter()

    # 捕获 Ctrl+C
    def handle_sigint(_sig, _frame):
        renderer.leave()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_sigint)

    last_advice = ""
    sessions_state = {}
    session_order = []  # 记录 session_id 首次出现顺序，锁定排序

    try:
        while True:
            # 1. 发现活跃对话流
            sessions = discoverer.discover()

            # 稳定排序：新 session 追加到末尾，已有 session 保持原位
            seen_ids = {s.session_id for s in sessions}
            # 清理已消失的 session
            session_order = [sid for sid in session_order if sid in seen_ids]
            # 追加新出现的 session
            for s in sessions:
                if s.session_id not in session_order:
                    session_order.append(s.session_id)
            # 按锁定顺序排列
            order_map = {sid: i for i, sid in enumerate(session_order)}
            sessions.sort(key=lambda s: order_map[s.session_id])

            # 2. 读取每个对话流的内容
            for session in sessions:
                reader.update(session)

            # 3. 检测状态变化
            changes = detector.detect(sessions, sessions_state)
            sessions_state = detector.snapshot(sessions)

            # 4. 每轮都调 generate()：内部非阻塞，自行管理限流和异步 CLI
            if sessions:
                force = changes.has_significant_change()
                # 仅在真正的状态转换时清空旧建议（新会话/完成/报错）
                # 工具切换(action_changed)太频繁，不清空
                if changes.new_sessions or changes.completed or changes.errors:
                    last_advice = ""
                result = advisor.generate(sessions, force=force)
                if result is not None:
                    last_advice = result
                # advisor 可能通过 _poll_pending 回填了 ai_task_description，
                # 同步回 reader 缓存，否则下轮会被旧缓存覆盖
                for session in sessions:
                    reader.sync_ai_description(session)

            if not sessions:
                last_advice = ""

            # 5. 重命名终端标签（内部限流，每 10 秒最多一次）
            renamer.rename(sessions)

            # 6. 渲染 TUI
            renderer.render(sessions, last_advice)

            time.sleep(2)

    except KeyboardInterrupt:
        pass
    finally:
        renderer.leave()


if __name__ == "__main__":
    main()
