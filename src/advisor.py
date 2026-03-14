"""建议生成器：通过 AI CLI 或规则引擎生成等待期建议。"""

import os
import random
import shutil
import subprocess
import time


class Advisor:
    """生成基于 WaitDex 策略的等待期建议。"""

    MIN_INTERVAL = 60  # 最短调用间隔（秒）

    def __init__(self):
        self._cli_path = shutil.which("claude")
        self._last_call_time = 0
        self._waitdex_sections = self._load_waitdex()

    def generate(self, sessions, force=False):
        """根据对话流状态生成建议文本。force=True 时跳过限流。"""
        if not sessions:
            return ""

        now = time.time()
        # 频率限制（由主循环控制 force 跳过）
        if not force and now - self._last_call_time < self.MIN_INTERVAL:
            return None  # 返回 None 表示不更新

        self._last_call_time = now

        # 构建状态描述
        status_block = self._build_status(sessions)

        # 优先 CLI 调用
        if self._cli_path:
            result = self._call_cli(status_block)
            if result:
                return result

        # 兜底规则引擎
        return self._rule_engine(sessions)

    def _build_status(self, sessions):
        """构建当前状态文本。"""
        blocks = []
        for s in sessions:
            wait_min = int(s.wait_seconds / 60) if s.wait_seconds else 0
            action = s.current_action or "处理中"
            files = ", ".join(os.path.basename(f) for f in s.files_involved[-5:]) if s.files_involved else "无"
            error = "无"
            if s.has_error:
                error = f"有：{s.error_message}" if s.error_message else "有"
            if s.is_completed:
                action = "已完成"

            ws = os.path.basename(s.workspace) if s.workspace else "未知"
            block = (
                f"- AI 工具：{'Claude Code' if s.cli_type == 'claude' else 'Codex'}\n"
                f"- 工作目录：{ws}\n"
                f"- 已等待：{wait_min} 分钟\n"
                f"- 当前动作：{action}\n"
                f"- 涉及文件：{files}\n"
                f"- 异常：{error}"
            )
            # 加入最近对话上下文
            if s.recent_messages:
                block += "\n- 最近对话："
                for msg in s.recent_messages[-4:]:
                    role = "用户" if msg["role"] == "user" else "AI"
                    block += f"\n  {role}：{msg['text']}"
            blocks.append(block)
        return "\n\n".join(blocks)

    def _build_prompt(self, status_block):
        """构建完整 prompt。"""
        waitdex = self._waitdex_sections
        prompt = (
            "你是一个轻松随意的等待期小助手。用户正在等 AI 编码工具跑完。\n\n"
            "根据下面的状态，给出：\n"
            "1. 一句话摘要：AI 在干嘛\n"
            "2. 1-3 条建议：用户现在可以干嘛（要具体、要轻松、随便挑一条就行）\n\n"
            "语气像朋友顺嘴一提，不要列清单，不要解释原因。\n"
        )
        if waitdex:
            prompt += f"\n{waitdex}\n"
        prompt += f"\n当前状态：\n{status_block}"
        return prompt

    def _call_cli(self, status_block):
        """通过 claude CLI 生成建议。"""
        prompt = self._build_prompt(status_block)
        try:
            result = subprocess.run(
                ["claude", "-p", "--no-session-persistence", prompt],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass
        return ""

    def _rule_engine(self, sessions):
        """纯规则引擎兜底。"""
        parts = []
        for s in sessions:
            cli = "Claude Code" if s.cli_type == "claude" else "Codex"
            wait_min = int(s.wait_seconds / 60) if s.wait_seconds else 0
            action = s.current_action or "处理中"
            recent_file = os.path.basename(s.files_involved[-1]) if s.files_involved else ""
            n_files = len(s.files_involved)

            if s.is_completed:
                summary = f"{cli} 已完成，改了 {n_files} 个文件"
                pool = []
                if recent_file:
                    pool.append(f"先看 {recent_file} 的 diff")
                pool.append("跑一遍测试确认没挂")
                tips = random.sample(pool, min(len(pool), 2))

            elif s.has_error:
                err_brief = s.error_message[:40] if s.error_message else "未知错误"
                summary = f"{cli} 遇到错误：{err_brief}"
                tips = random.sample([
                    "可能需要你介入看一眼",
                    "检查一下报错信息再决定下一步",
                ], 1)

            elif wait_min >= 5 and self._is_stale(s):
                summary = f"{cli} 好像卡住了（{wait_min} 分钟没动静）"
                tips = random.sample([
                    "可能需要你看一眼终端",
                    "考虑是不是要中断重试",
                ], 1)

            elif wait_min < 2:
                summary = f"{cli} 正在 {action}，刚开始"
                tips = random.sample([
                    "站起来活动一下",
                    "喝口水",
                    "看看远处让眼睛休息",
                ], 2)

            elif wait_min <= 10:
                summary = f"{cli} 正在 {action}，已跑 {wait_min} 分钟"
                pool = ["顺手写下一条 prompt", "整理一下 TODO"]
                if recent_file:
                    pool.insert(0, f"看看 {recent_file} 的 diff")
                tips = random.sample(pool, min(len(pool), 2))

            else:
                summary = f"{cli} 已跑 {wait_min} 分钟，可能是个大活"
                tips = random.sample([
                    "回条消息",
                    "补一小段文档",
                    "清理一下浏览器标签页",
                ], 2)

            tip_text = "\n".join(f"· {t}" for t in tips)
            parts.append(f"{summary}\n{tip_text}")

        return "\n\n".join(parts)

    def _is_stale(self, session):
        """检查文件是否 5 分钟无更新。"""
        try:
            mtime = os.path.getmtime(session.file_path)
            return time.time() - mtime > 300
        except OSError:
            return False

    def _load_waitdex(self):
        """从 WaitDex.md 提取 ## 3. / ## 4. / ## 9. 开头的 section。"""
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        waitdex_path = os.path.join(project_root, "WaitDex.md")
        try:
            with open(waitdex_path, "r", encoding="utf-8") as f:
                content = f.read()
        except OSError:
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
