"""Terminal tab renaming module (terminal_renamer)

Automatically detects terminal tab working directories and renames tabs running
AI CLI to the project name, solving the problem of multiple tabs all showing
"claude" / "codex" with no way to tell them apart.

Supports: Ghostty (AppleScript API to read working directory, requires v1.3+),
Terminal.app (AppleScript tty + lsof to infer working directory).
"""

import os
import subprocess
import time


class TerminalRenamer:
    """Detects terminal tabs and renames them to project names."""

    MIN_INTERVAL = 10  # seconds

    def __init__(self):
        self._last_run = 0

    def rename(self, sessions):
        """Rename terminal tabs. Runs at most once per MIN_INTERVAL seconds."""
        now = time.time()
        if now - self._last_run < self.MIN_INTERVAL:
            return
        self._last_run = now

        # workspace path -> project basename (only sessions with live CLI processes)
        ws_names = {}
        if sessions:
            for s in sessions:
                if s.workspace and s.has_live_process:
                    ws_names[s.workspace] = os.path.basename(s.workspace)

        # Active project names that SHOULD be pinned right now
        active_names = set(ws_names.values())

        # Unpin stale tabs, then pin active ones (both run every cycle)
        self._cleanup_ghostty(active_names)
        self._cleanup_terminal_app(active_names)

        if ws_names:
            self._rename_ghostty(ws_names)
            self._rename_terminal_app(ws_names)

    def _rename_ghostty(self, ws_names):
        """Ghostty: pin tab title via perform action "set_tab_title:...".

        Uses Ghostty's set_tab_title action (not direct name property),
        which pins the title so it won't be overridden by CLI process OSC escape sequences.
        """
        if not self._is_app_running("Ghostty"):
            return

        # Dynamically generate if/else conditions: match cwd then perform action
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
        """Terminal.app: infer working directory via tty + lsof and rename."""
        if not self._is_app_running("Terminal"):
            return

        # Get tty of tabs running CC/Codex (filtered by tab name) in one call
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

    def _cleanup_ghostty(self, active_names):
        """Ghostty: unpin any tab whose title was set by us but no longer matches
        an active session. Uses a negative check — if a tab title is NOT a known
        Ghostty/shell default AND NOT in active_names, it was likely pinned by us
        and should be unpinned.

        We identify our pinned tabs by: title does not contain "Claude Code",
        "Codex", or common shell defaults (zsh/bash/~), AND is not in active_names.
        To be safe, only unpin tabs whose cwd no longer has a running AI CLI
        (i.e., the cwd doesn't match any active workspace).
        """
        if not self._is_app_running("Ghostty"):
            return

        # Build a whitelist of titles we should NOT unpin
        keep_conditions = [
            'tname contains "Claude Code"',
            'tname contains "Codex"',
        ]
        for name in active_names:
            safe_name = name.replace("\\", "\\\\").replace('"', '\\"')
            keep_conditions.append(f'tname is "{safe_name}"')

        keep_check = " or ".join(keep_conditions)

        # For tabs NOT in the whitelist: check if they look like a pinned
        # project name (short, no path separators) and unpin them.
        # The "tname does not contain /" heuristic avoids touching tabs with
        # shell-generated titles like "/Users/foo" or "~/projects".
        script = (
            'tell application "Ghostty"\n'
            "    repeat with win in windows\n"
            "        repeat with t in tabs of win\n"
            "            try\n"
            "                set tname to name of t\n"
            f'                if not ({keep_check}) and tname does not contain "/" and tname does not contain "~" then\n'
            "                    set term to focused terminal of t\n"
            '                    perform action "set_tab_title:" on term\n'
            "                end if\n"
            "            end try\n"
            "        end repeat\n"
            "    end repeat\n"
            "end tell"
        )
        self._run_osascript(script)

    def _cleanup_terminal_app(self, active_names):
        """Terminal.app: clear custom title for tabs we previously renamed
        but that no longer match an active session."""
        if not self._is_app_running("Terminal"):
            return

        keep_conditions = []
        for name in active_names:
            safe_name = name.replace("\\", "\\\\").replace('"', '\\"')
            keep_conditions.append(f'tname is "{safe_name}"')

        # Only act on tabs that have a non-empty custom title not in active_names
        if keep_conditions:
            keep_check = " or ".join(keep_conditions)
            skip_condition = f'if tname is "" or ({keep_check}) then\n                    -- keep\n                else'
        else:
            skip_condition = 'if tname is "" then\n                    -- keep\n                else'

        script = (
            'tell application "Terminal"\n'
            "    repeat with w from 1 to count of windows\n"
            "        repeat with t from 1 to count of tabs of window w\n"
            "            try\n"
            "                set tname to custom title of tab t of window w\n"
            f"                {skip_condition}\n"
            '                    set custom title of tab t of window w to ""\n'
            "                    set title displays custom title of tab t of window w to false\n"
            "                end if\n"
            "            end try\n"
            "        end repeat\n"
            "    end repeat\n"
            "end tell"
        )
        self._run_osascript(script)

    def _get_tty_cwd(self, tty):
        """Get the working directory of processes on a tty via lsof."""
        try:
            # Find processes on this tty (take smallest PID, usually the shell)
            r = subprocess.run(
                ["lsof", "-t", tty],
                capture_output=True, text=True, timeout=3,
            )
            if r.returncode != 0 or not r.stdout.strip():
                return ""

            pid = r.stdout.strip().split("\n")[0].strip()

            # Get working directory of that process
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
        """Check if an application is running (won't launch it)."""
        output = self._run_osascript(
            f'tell application "System Events" to return '
            f'(name of every process whose name is "{app_name}") as text'
        )
        return bool(output)

    def _run_osascript(self, script):
        """Execute osascript, return output or empty string."""
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
