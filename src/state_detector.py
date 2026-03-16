"""State change detection module (state_detector)

Compares session states between adjacent polling cycles to detect meaningful
change events: new sessions appearing, sessions completing, new errors,
action switches, and prolonged inactivity (stale).

Detection results are encapsulated in a Changes object, used by the main loop
to determine whether to force-refresh advice. The snapshot() method generates
the current cycle's state snapshot as the comparison baseline for the next cycle.
"""

import os
import time


class Changes:
    """Summary of changes detected in one cycle."""

    def __init__(self):
        self.new_sessions = []       # newly discovered session_ids
        self.completed = []          # just-completed session_ids
        self.errors = []             # newly errored session_ids
        self.stale = []              # long-inactive session_ids
        self.action_changed = []     # action-switched session_ids

    def has_significant_change(self):
        return bool(
            self.new_sessions or self.completed
            or self.errors or self.stale or self.action_changed
        )


class StateDetector:
    """Detects state changes in sessions."""

    STALE_THRESHOLD = 300  # 5 minutes without changes

    def detect(self, sessions, prev_state):
        """Compare current sessions against previous snapshot, return Changes."""
        changes = Changes()
        now = time.time()
        current_ids = {s.session_id for s in sessions}
        prev_ids = set(prev_state.keys())

        # New sessions
        for sid in current_ids - prev_ids:
            changes.new_sessions.append(sid)

        for s in sessions:
            prev = prev_state.get(s.session_id)
            if prev is None:
                continue

            # Completed
            if s.is_completed and not prev.get("is_completed"):
                changes.completed.append(s.session_id)

            # Error
            if s.has_error and not prev.get("has_error"):
                changes.errors.append(s.session_id)

            # Action changed
            if s.current_action and s.current_action != prev.get("current_action", ""):
                changes.action_changed.append(s.session_id)

            # Stale (completed sessions don't count as stale)
            if not s.is_completed:
                try:
                    mtime = os.path.getmtime(s.file_path)
                    if now - mtime > self.STALE_THRESHOLD:
                        changes.stale.append(s.session_id)
                except OSError:
                    pass

        return changes

    def snapshot(self, sessions):
        """Generate state snapshot for the current cycle."""
        state = {}
        for s in sessions:
            state[s.session_id] = {
                "is_completed": s.is_completed,
                "has_error": s.has_error,
                "current_action": s.current_action,
            }
        return state
