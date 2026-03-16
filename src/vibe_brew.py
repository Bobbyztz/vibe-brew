"""Main entry module (vibe_brew)

The sole entry point for vibe-brew. After installation, run `vibe-brew` to start.
Contains the main loop and TUI renderer:

The main loop runs a pipeline every 2 seconds: discover active sessions -> read content
-> detect state changes -> generate advice -> render TUI. Session list uses stable
ordering (new sessions appended at the end, existing sessions keep their position)
to avoid TUI flickering.

The Renderer class uses an alternate screen buffer for full-screen TUI, supports CJK
character width calculation, session state icons, advice display area, and graceful
Ctrl+C exit with terminal restoration.
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
from .i18n import init_lang, detect_from_sessions, t, get_error_templates


class Renderer:
    """Terminal TUI renderer using alternate screen buffer."""

    def __init__(self):
        self._in_alt_screen = False

    def enter(self):
        """Enter alternate screen buffer."""
        sys.stdout.write("\033[?1049h")  # enter
        sys.stdout.write("\033[?25l")    # hide cursor
        sys.stdout.flush()
        self._in_alt_screen = True

    def leave(self):
        """Leave alternate screen buffer, restore terminal."""
        if self._in_alt_screen:
            sys.stdout.write("\033[?25h")    # show cursor
            sys.stdout.write("\033[?1049l")  # leave
            sys.stdout.flush()
            self._in_alt_screen = False

    def render(self, sessions, advice):
        """Render one TUI frame."""
        try:
            cols = os.get_terminal_size().columns
        except OSError:
            cols = 80
        cols = max(cols, 40)

        lines = []

        # Title bar
        title = " vibe-brew "
        pad = cols - len(title) - 2
        left_pad = pad // 2
        right_pad = pad - left_pad
        lines.append("\u2554" + "\u2550" * left_pad + title + "\u2550" * right_pad + "\u2557")
        lines.append("\u2551" + " " * (cols - 2) + "\u2551")

        if not sessions:
            msg = t("no_sessions")
            msg_pad = cols - 2 - self._display_width(msg)
            lines.append("\u2551 " + msg + " " * max(msg_pad - 1, 0) + "\u2551")
        else:
            for i, s in enumerate(sessions):
                # Status icon (completed takes priority over error)
                if s.is_completed:
                    icon = "\u25cf"
                elif s.has_error:
                    icon = "\u26a0"
                else:
                    icon = "\u27f3"

                cli_name = "Claude Code" if s.cli_type == "claude" else "Codex"
                ws_short = os.path.basename(s.workspace) if s.workspace else "?"

                task = s.ai_task_description or s.task_summary or ""
                task_part = f" \u00b7 {task}" if task else ""
                header = f" {icon} {cli_name} \u00b7 {ws_short}{task_part}"
                header_line = self._pad_line(header, cols)
                lines.append("\u2551" + header_line + "\u2551")

                # Status detail + elapsed time (e.g. "Running 5min")
                detail = self._format_status(s)
                if not s.is_completed and s.wait_seconds:
                    if s.wait_seconds < 60:
                        detail += f" {int(s.wait_seconds)}s"
                    else:
                        detail += f" {int(s.wait_seconds / 60)}min"
                for dl in self._wrap_lines(f"   {detail}", cols, indent=3, max_lines=2):
                    lines.append("\u2551" + self._pad_line(dl, cols) + "\u2551")

                # Show current tool action when in progress (e.g. Read main.py)
                if not s.is_completed and s.current_action:
                    action_line = self._pad_line(f"   \u2192 {s.current_action}", cols)
                    lines.append("\u2551" + action_line + "\u2551")

                # Blank line between sessions
                if i < len(sessions) - 1:
                    lines.append("\u2551" + " " * (cols - 2) + "\u2551")

        # Bottom of monitor area + separator + top of advice area
        lines.append("\u2551" + " " * (cols - 2) + "\u2551")
        lines.append("\u2560" + "\u2500" * (cols - 2) + "\u2563")
        lines.append("\u2551" + " " * (cols - 2) + "\u2551")

        # Advice area (supports wrapping, blank line between items for breathing room)
        if advice:
            advice_lines = advice.split("\n")
            for i, aline in enumerate(advice_lines):
                content = f" {aline}"
                for wl in self._wrap_lines(content, cols, indent=3, max_lines=2):
                    padded = self._pad_line(wl, cols)
                    lines.append("\u2551" + padded + "\u2551")
                if i < len(advice_lines) - 1:
                    lines.append("\u2551" + " " * (cols - 2) + "\u2551")
        else:
            hint = " " + t("generating")
            lines.append("\u2551" + self._pad_line(hint, cols) + "\u2551")

        # Footer
        lines.append("\u2551" + " " * (cols - 2) + "\u2551")
        footer = " " + t("exit_hint")
        lines.append("\u255a" + "\u2550" * (cols - 2 - self._display_width(footer)) + footer + "\u255d")

        # Output
        output = "\033[H"  # cursor home
        output += "\n".join(lines)
        # Clear remaining lines
        try:
            rows = os.get_terminal_size().lines
        except OSError:
            rows = 24
        remaining = rows - len(lines)
        if remaining > 0:
            output += "\n" + "\033[K\n" * remaining

        sys.stdout.write(output)
        sys.stdout.flush()

    def _format_status(self, session):
        """Generate panel status description text.

        The monitor area shows only concise status; task description is shown
        in the advice area. Error details are kept for quick identification.
        """
        if session.is_completed:
            return t("status_done")
        elif session.has_error:
            desc = session.ai_task_description
            fallback = session.task_summary
            if desc:
                return self._pick_tpl(get_error_templates(), session.session_id, desc)
            err = session.error_message[:20] if session.error_message else ""
            if err:
                return t("error_with_msg").format(err=err)
            if fallback:
                return t("error_with_task").format(task=fallback)
            return t("status_error")
        else:
            return t("status_running")

    # CJK punctuation and spaces, suitable for line-breaking after
    _BREAK_AFTER = set(" \t,.;!?\u3001\uff09\u3011\u300b\u300d\u300f\uff1a\uff0c\u3002\uff1b\uff01\uff1f")

    def _wrap_lines(self, text, cols, indent=3, max_lines=2):
        """Wrap text by display width, preferring breaks after spaces/punctuation.

        Lines after the first are indented by indent+2 spaces, up to max_lines.
        """
        avail = cols - 2  # two sides for box chars
        if self._display_width(text) <= avail:
            return [text]

        # Scan char by char, tracking the best break point
        best_break = 0
        best_break_w = 0
        w = 0
        for i, ch in enumerate(text):
            cw = 2 if ord(ch) > 0x7F else 1
            w += cw
            if ch in self._BREAK_AFTER:
                best_break = i + 1
                best_break_w = w
            if w > avail:
                if best_break > 0 and best_break_w > avail * 0.4:
                    split = best_break
                else:
                    split = i
                line1 = text[:split]
                prefix = " " * (indent + 2)
                line2 = prefix + text[split:].lstrip()
                return [line1, line2][:max_lines]

        return [text]

    def _pick_tpl(self, templates, session_id, summary):
        """Pick a template stably by session_id hash, so the same session
        doesn't change template every frame."""
        idx = hash(session_id) % len(templates)
        return templates[idx].format(s=summary)

    def _pad_line(self, text, cols):
        """Pad text to cols-2 display width, ensuring single-line safety."""
        # Defense against multi-line content: take only the first line
        text = text.split("\n")[0]
        target = cols - 2
        width = self._display_width(text)
        if width < target:
            return text + " " * (target - width)
        elif width > target:
            # Truncate by display width (not char count) to avoid cutting CJK chars in half
            result = []
            w = 0
            for ch in text:
                cw = 2 if ord(ch) > 0x7F else 1
                if w + cw > target - 1:  # reserve 1 col for ellipsis
                    result.append("\u2026")
                    break
                result.append(ch)
                w += cw
            truncated = "".join(result)
            pad = target - self._display_width(truncated)
            return truncated + " " * max(pad, 0)
        return text

    def _display_width(self, text):
        """Roughly calculate display width (CJK characters take 2 columns)."""
        w = 0
        for ch in text:
            if ord(ch) > 0x7F:
                w += 2
            else:
                w += 1
        return w


def main():
    # Parse --lang flag
    lang_arg = None
    args = sys.argv[1:]
    if "--lang" in args:
        idx = args.index("--lang")
        if idx + 1 < len(args):
            lang_arg = args[idx + 1]

    # Initialize language (must happen before Advisor, which loads WaitDex)
    init_lang(lang_arg)

    discoverer = SessionDiscoverer()
    reader = ContentReader()
    detector = StateDetector()
    advisor = Advisor()
    renderer = Renderer()
    renamer = TerminalRenamer()

    # Enter alternate screen
    renderer.enter()

    # Catch Ctrl+C
    def handle_sigint(_sig, _frame):
        renderer.leave()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_sigint)

    last_advice = ""
    sessions_state = {}
    session_order = []  # Track session_id first-seen order to lock sorting

    try:
        while True:
            # 1. Discover active sessions
            sessions = discoverer.discover()

            # Stable sort: new sessions appended at end, existing sessions keep position
            seen_ids = {s.session_id for s in sessions}
            # Remove disappeared sessions
            session_order = [sid for sid in session_order if sid in seen_ids]
            # Append newly appeared sessions
            for s in sessions:
                if s.session_id not in session_order:
                    session_order.append(s.session_id)
            # Sort by locked order
            order_map = {sid: i for i, sid in enumerate(session_order)}
            sessions.sort(key=lambda s: order_map[s.session_id])

            # 2. Read content for each session
            for session in sessions:
                reader.update(session)

            # 2.5. Auto-detect language from session content (only in auto mode)
            if detect_from_sessions(sessions):
                # Language changed — reinitialize advisor to reload WaitDex
                advisor = Advisor()

            # 3. Detect state changes
            changes = detector.detect(sessions, sessions_state)
            sessions_state = detector.snapshot(sessions)

            # 4. Call generate() every cycle: internally non-blocking, self-manages rate limiting and async CLI
            if sessions:
                force = changes.has_significant_change()
                # Only clear old advice on real state transitions (new session/completed/error)
                # Tool switches (action_changed) are too frequent, don't clear
                if changes.new_sessions or changes.completed or changes.errors:
                    last_advice = ""
                result = advisor.generate(sessions, force=force)
                if result is not None:
                    last_advice = result
                # Advisor may have backfilled ai_task_description via _poll_pending;
                # sync back to reader cache, otherwise next cycle's cache restore overwrites
                for session in sessions:
                    reader.sync_ai_description(session)

            if not sessions:
                last_advice = ""

            # 5. Rename terminal tabs (internally rate-limited, at most once per 10s)
            renamer.rename(sessions)

            # 6. Render TUI
            renderer.render(sessions, last_advice)

            time.sleep(2)

    except KeyboardInterrupt:
        pass
    finally:
        renderer.leave()


if __name__ == "__main__":
    main()
