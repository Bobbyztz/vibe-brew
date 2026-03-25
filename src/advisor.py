"""Advice generation module (advisor)

Generates wait-time suggestions based on current session states. Uses a dual-engine
strategy:
- Primarily calls the installed claude CLI asynchronously via subprocess (injecting
  WaitDex strategy as in-context learning context) to generate personalized advice;
- When CLI is unavailable or while waiting for CLI response, falls back to a pure
  rule engine that randomly selects from preset tip pools based on wait duration.

Rate limiting (MIN_INTERVAL=30s) and async polling ensure the main loop is not blocked.
WaitDex.md is loaded at initialization, extracting sections 3/4/9 as strategy context.
"""

import importlib.resources
import os
import random
import shutil
import subprocess
import time

from .i18n import get_lang, get_tips, get_rule_status


class Advisor:
    """Generates WaitDex-based wait-time advice."""

    MIN_INTERVAL = 30  # minimum call interval (seconds)

    def __init__(self):
        self._cli_path = shutil.which("claude")
        self._last_call_time = 0
        self._waitdex_sections = self._load_waitdex()
        self._pending_proc = None  # async CLI subprocess
        self._pending_start = 0
        self._pending_sessions = []  # sessions at time of request
        self._tip_bags = {}  # duration -> remaining shuffled tips
        self._last_tip = {}  # duration -> last drawn tip (for boundary dedup)

    def generate(self, sessions, force=False):
        """Generate advice text based on session states. Non-blocking: CLI called async, results polled."""
        if not sessions:
            self._cancel_pending()
            return ""

        # Check if async CLI has returned a result
        cli_result = self._poll_pending(sessions)
        if cli_result:
            return cli_result

        # If CLI is still running, don't start a new request
        if self._pending_proc is not None:
            return None

        now = time.time()
        if not force and now - self._last_call_time < self.MIN_INTERVAL:
            return None

        self._last_call_time = now
        self._pending_sessions = sessions  # record sessions for this request
        status_block = self._build_status(sessions)

        # Prefer async CLI call
        if self._cli_path:
            self._start_cli(status_block, len(sessions))
            # Return rule engine result immediately as a transition
            return self._rule_engine(sessions)

        return self._rule_engine(sessions)

    def _start_cli(self, status_block, n_sessions):
        """Start CLI subprocess non-blocking."""
        prompt = self._build_prompt(status_block, n_sessions)
        try:
            self._pending_proc = subprocess.Popen(
                ["claude", "-p", "--no-session-persistence",
                 "--model", "claude-haiku-4-5-20251001", prompt],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, preexec_fn=os.setpgrp,
            )
            self._pending_start = time.time()
        except (FileNotFoundError, OSError):
            self._pending_proc = None

    def _poll_pending(self, sessions=None):
        """Non-blocking check if subprocess is done, return result or None.

        Parses "desc|windowN:..." lines from CLI output, backfills them into
        corresponding session ai_task_description fields; remaining lines
        are returned as advice text.
        """
        if self._pending_proc is None:
            return None

        ret = self._pending_proc.poll()
        if ret is None:
            # Still running, check timeout
            if time.time() - self._pending_start > 30:
                self._cancel_pending()
            return None

        # Subprocess finished
        stdout = self._pending_proc.stdout.read()
        self._pending_proc = None
        if ret != 0 or not stdout.strip():
            return None

        # Parse: separate description lines from advice lines
        desc_lines = {}  # window number (1-based) -> description text
        advice_lines = []
        for line in stdout.strip().split("\n"):
            stripped = line.strip()
            if stripped.startswith("desc|window"):
                # "desc|window1: fixing a bug" -> key=1, val="fixing a bug"
                rest = stripped[len("desc|window"):]
                sep = rest.find(":")
                if sep > 0:
                    try:
                        idx = int(rest[:sep])
                        desc_lines[idx] = rest[sep + 1:].strip()
                    except ValueError:
                        pass
            elif stripped and not all(c in "-=_*#" for c in stripped):
                # Skip empty lines, pure formatting lines (---, ===, etc.),
                # and echoed status block lines (CLI sometimes echoes the input)
                if stripped.startswith("[Window ") and ":" in stripped:
                    continue
                if stripped.startswith("- ") and any(
                    stripped.startswith(p)
                    for p in ("- Task:", "- Phase:", "- Waiting:", "- Files involved:")
                ):
                    continue
                advice_lines.append(line)

        # Backfill AI descriptions to sessions
        target = sessions if sessions else self._pending_sessions
        if desc_lines and target:
            for i, s in enumerate(target, 1):
                if i in desc_lines:
                    s.ai_task_description = desc_lines[i]

        return "\n".join(advice_lines).strip() or None

    def _cancel_pending(self):
        """Cancel an in-progress CLI call."""
        if self._pending_proc is not None:
            try:
                self._pending_proc.kill()
                self._pending_proc.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                pass
            self._pending_proc = None

    def _build_status(self, sessions):
        """Build current status text, each session with a numbered label."""
        blocks = []
        for i, s in enumerate(sessions, 1):
            wait_min = int(s.wait_seconds / 60) if s.wait_seconds else 0
            # Phase determination
            if s.is_completed:
                phase = "Completed"
            elif s.has_error:
                phase = f"Error: {s.error_message}" if s.error_message else "Error"
            else:
                phase = "Running"

            cli_name = "Claude Code" if s.cli_type == "claude" else "Codex"
            ws = os.path.basename(s.workspace) if s.workspace else "unknown"
            task = s.task_summary or "unknown task"
            files = ", ".join(os.path.basename(f) for f in s.files_involved[-5:]) if s.files_involved else "none"

            block = (
                f"[Window {i}: {ws} \u00b7 {cli_name}]\n"
                f"- Task: {task}\n"
                f"- Phase: {phase}\n"
                f"- Waiting: {wait_min} min\n"
                f"- Files involved: {files}"
            )
            blocks.append(block)
        return "\n\n".join(blocks)

    def _build_prompt(self, status_block, n_sessions):
        """Build the complete prompt."""
        waitdex = self._waitdex_sections
        lang = get_lang()

        if lang == "zh":
            lang_instruction = (
                "IMPORTANT: Reply entirely in Chinese (Simplified). "
                "Even if the task description or status contains English, "
                "your suggestions and desc lines MUST be in Chinese.\n\n"
            )
            examples = (
                "## Suggestion examples\n"
                "- Running: \"\u00b7 \u5750\u4e86\u4e00\u4f1a\u513f\u4e86\uff0c\u8d77\u6765\u6d3b\u52a8\u6d3b\u52a8\u5427\uff01\"\n"
                "- Completed: \"\u00b7 Trading-Burger \u5b8c\u6210\u4e86\u3002\u559d\u53e3\u6c34\uff0c\u7136\u540e\u770b\u770b diff\"\n"
                "- Error: \"\u00b7 Trading-Burger \u9047\u5230\u4e86\u70b9\u95ee\u9898\uff0c\u4e0d\u6025\u2014\u2014\u6709\u7a7a\u518d\u770b\u770b\"\n\n"
            )
            bad_good = "  (\u00d7\"\u8d77\u6765\u52a8\u4e00\u52a8\" \u2192 \u25cb\"\u5750\u4e86\u4e00\u4f1a\u513f\u4e86\uff0c\u8d77\u6765\u6d3b\u52a8\u6d3b\u52a8\u5427\uff01\")\n"
        else:
            lang_instruction = (
                "IMPORTANT: Reply entirely in English. "
                "Even if the task description or status contains non-English text, "
                "your suggestions and desc lines MUST be in English.\n\n"
            )
            examples = (
                "## Suggestion examples\n"
                "- Running: \"\u00b7 You've been at it for a while, stretch your legs!\"\n"
                "- Completed: \"\u00b7 Trading-Burger is done. Grab some water, then check the diff\"\n"
                "- Error: \"\u00b7 Trading-Burger hit a snag, no rush -- take a look when you're back\"\n\n"
            )
            bad_good = "  (\u00d7\"Stand up and move\" \u2192 \u25cb\"You've been at it for a while, stretch your legs!\")\n"

        common_rules = (
            "You are a friendly, casual wait-time assistant.\n\n"
            + lang_instruction
            + "## Panel structure (you must understand this context)\n"
            "The panel has two sections:\n"
            "- Monitor area: status icon + CLI name + project name + task description + status + duration\n"
            "  Task description is already shown in the monitor area, no need to repeat in advice\n"
            "- Advice area: your output goes here, focus only on caring suggestions\n\n"
            "## Output format (follow strictly)\n"
            "1. First output one task description line per window (for monitor area backfill), "
            "format: \"desc|windowN: bare action description\"\n"
            "   Bare action description: 10 words or less, from AI's perspective "
            "(\u00d7\"handling user's bug\" \u2192 \u25cb\"debugging login issue\")\n"
            "2. Then output 1-3 caring suggestions, format: \"\u00b7 suggestion\"\n"
            "   Advice area should not include project name or task description, only caring and action suggestions\n\n"
            + examples
            + "## Suggestion rules\n"
            "- Task description is in the monitor area, advice area only needs caring suggestions "
            "(can mention project name for completed/error)\n"
            "- Tone should be warm and friendly, like a friend checking in -- care for the person first, "
            "then mention the task\n"
            "- Suggesting rest is always valid, but add warmth and context\n"
            + bad_good
            + "- Differentiate by session phase:\n"
            "  \u00b7 Completed: care for the person first (water, stretch), then mention review\n"
            "  \u00b7 Error: gentle reassurance, no rush, just take a look when ready\n"
            "  \u00b7 Running: don't suggest looking at specific files (you don't know overall progress),\n"
            "    instead suggest physical recovery, preparing for next round, or light maintenance\n"
            "- Adjust by wait duration: <2min lean toward physical recovery, 2-10min lean toward next-round prep, "
            ">10min can do light self-contained tasks\n"
        )
        if n_sessions > 1:
            prompt = common_rules + "The user is waiting on multiple AI coding tools simultaneously.\n"
        else:
            prompt = common_rules + "The user is waiting for an AI coding tool to finish.\n"
        if waitdex:
            prompt += f"\n{waitdex}\n"
        prompt += f"\nCurrent status:\n{status_block}"
        return prompt

    def _rule_engine(self, sessions):
        """Pure rule engine fallback. Task description is in monitor area,
        advice area only outputs caring suggestions."""
        lines = []
        has_active = False
        status_index = 0  # increments per status line for template diversity

        for s in sessions:
            ws = os.path.basename(s.workspace) if s.workspace else ""
            recent_file = os.path.basename(s.files_involved[-1]) if s.files_involved else ""
            wait_min = int(s.wait_seconds / 60) if s.wait_seconds else 0

            if s.is_completed:
                if recent_file:
                    lines.append(get_rule_status("done_with_file", index=status_index, ws=ws, f=recent_file))
                else:
                    lines.append(get_rule_status("done_no_file", index=status_index, ws=ws))
                status_index += 1
            elif s.has_error:
                lines.append(get_rule_status("error", index=status_index, ws=ws))
                status_index += 1
            elif wait_min >= 5 and self._is_stale(s):
                lines.append(get_rule_status("stale", index=status_index, ws=ws))
                status_index += 1
            else:
                has_active = True

        # For active sessions, pick a caring tip via shuffle bag
        if has_active and len(lines) < 3:
            max_wait = max(
                (int(s.wait_seconds / 60) if s.wait_seconds else 0)
                for s in sessions if not s.is_completed and not s.has_error
            )
            if max_wait < 2:
                duration = "short"
            elif max_wait <= 10:
                duration = "medium"
            else:
                duration = "long"
            tip = self._draw_tip(duration)
            if tip not in lines:
                lines.append(tip)

        # Deduplicate, max 3 items
        seen = []
        for item in lines:
            if item not in seen:
                seen.append(item)
            if len(seen) >= 3:
                break

        return "\n".join(f"\u00b7 {item}" for item in seen)

    def _draw_tip(self, duration):
        """Draw a tip from the shuffle bag for the given duration bucket.

        Exhausts all tips before reshuffling. On reshuffle, ensures the first
        draw differs from the last draw of the previous round.
        """
        bag = self._tip_bags.get(duration)
        if not bag:
            pool = list(get_tips(duration))
            random.shuffle(pool)
            # Avoid boundary repeat: if last item to be popped equals previous draw, rotate
            prev = self._last_tip.get(duration)
            if prev and len(pool) > 1 and pool[-1] == prev:
                pool.insert(0, pool.pop())
            self._tip_bags[duration] = pool
            bag = self._tip_bags[duration]
        tip = bag.pop()
        self._last_tip[duration] = tip
        return tip

    def _is_stale(self, session):
        """Check if file hasn't been updated in 5 minutes (completed sessions don't count as stale)."""
        if session.is_completed:
            return False
        try:
            mtime = os.path.getmtime(session.file_path)
            return time.time() - mtime > 300
        except OSError:
            return False

    def _load_waitdex(self):
        """Extract sections starting with ## 3. / ## 4. / ## 9. from WaitDex.md."""
        filename = "WaitDex.md" if get_lang() == "zh" else "WaitDex_en.md"
        try:
            ref = importlib.resources.files("src").joinpath(filename)
            content = ref.read_text(encoding="utf-8")
        except (OSError, FileNotFoundError, ModuleNotFoundError):
            return ""

        sections = []
        current = None
        for line in content.split("\n"):
            if line.startswith("## "):
                title = line[3:].strip()
                if title.startswith(("3.", "4.", "9.")):
                    current = [line]
                else:
                    if current:
                        sections.append("\n".join(current))
                    current = None
            elif current is not None:
                current.append(line)
        if current:
            sections.append("\n".join(current))

        return "\n\n".join(sections)
