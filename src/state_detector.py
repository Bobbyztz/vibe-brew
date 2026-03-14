"""状态变化检测器：对比前后轮次，检测对话流状态变化。"""

import os
import time


class Changes:
    """一轮检测的变化摘要。"""

    def __init__(self):
        self.new_sessions = []       # 新发现的 session_id
        self.completed = []          # 刚完成的 session_id
        self.errors = []             # 新报错的 session_id
        self.stale = []              # 长时间无变化的 session_id
        self.action_changed = []     # 动作切换的 session_id

    def has_significant_change(self):
        return bool(
            self.new_sessions or self.completed
            or self.errors or self.stale or self.action_changed
        )


class StateDetector:
    """检测对话流状态变化。"""

    STALE_THRESHOLD = 300  # 5 分钟无变化

    def detect(self, sessions, prev_state):
        """对比当前 sessions 和上一轮快照，返回 Changes。"""
        changes = Changes()
        now = time.time()
        current_ids = {s.session_id for s in sessions}
        prev_ids = set(prev_state.keys())

        # 新对话流
        for sid in current_ids - prev_ids:
            changes.new_sessions.append(sid)

        for s in sessions:
            prev = prev_state.get(s.session_id)
            if prev is None:
                continue

            # 完成
            if s.is_completed and not prev.get("is_completed"):
                changes.completed.append(s.session_id)

            # 报错
            if s.has_error and not prev.get("has_error"):
                changes.errors.append(s.session_id)

            # 动作切换
            if s.current_action and s.current_action != prev.get("current_action", ""):
                changes.action_changed.append(s.session_id)

            # 长时间无变化
            try:
                mtime = os.path.getmtime(s.file_path)
                if now - mtime > self.STALE_THRESHOLD:
                    changes.stale.append(s.session_id)
            except OSError:
                pass

        return changes

    def snapshot(self, sessions):
        """生成当前轮次的状态快照。"""
        state = {}
        for s in sessions:
            state[s.session_id] = {
                "is_completed": s.is_completed,
                "has_error": s.has_error,
                "current_action": s.current_action,
            }
        return state
