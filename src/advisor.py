"""建议生成模块 (advisor)

负责根据当前对话流状态生成等待期建议。采用双引擎策略：
- 优先通过 subprocess 异步调用已安装的 claude CLI（注入 WaitDex 策略作为
  in-context learning 上下文），生成个性化建议；
- CLI 不可用或等待 CLI 返回期间，使用纯规则引擎兜底，按等待时长从预置
  建议池中随机选取建议。

调用限流（MIN_INTERVAL=30s）和异步轮询机制确保不阻塞主循环。
WaitDex.md 在初始化时加载，提取其中第 3/4/9 节作为策略上下文。
"""

import importlib.resources
import os
import random
import shutil
import subprocess
import time


class Advisor:
    """生成基于 WaitDex 策略的等待期建议。"""

    MIN_INTERVAL = 30  # 最短调用间隔（秒）

    def __init__(self):
        self._cli_path = shutil.which("claude")
        self._last_call_time = 0
        self._waitdex_sections = self._load_waitdex()
        self._pending_proc = None  # 异步 CLI 子进程
        self._pending_start = 0
        self._pending_sessions = []  # 发起请求时对应的 sessions

    def generate(self, sessions, force=False):
        """根据对话流状态生成建议文本。非阻塞：CLI 异步调用，轮询收结果。"""
        if not sessions:
            self._cancel_pending()
            return ""

        # 先检查异步 CLI 是否已返回结果
        cli_result = self._poll_pending(sessions)
        if cli_result:
            return cli_result

        # 如果 CLI 还在跑，不发起新请求
        if self._pending_proc is not None:
            return None

        now = time.time()
        if not force and now - self._last_call_time < self.MIN_INTERVAL:
            return None

        self._last_call_time = now
        self._pending_sessions = sessions  # 记录本次请求的 sessions
        status_block = self._build_status(sessions)

        # 优先异步 CLI 调用
        if self._cli_path:
            self._start_cli(status_block, len(sessions))
            # 首次立刻返回规则引擎结果作为过渡
            return self._rule_engine(sessions)

        return self._rule_engine(sessions)

    def _start_cli(self, status_block, n_sessions):
        """非阻塞启动 CLI 子进程。"""
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
        """非阻塞检查子进程是否完成，返回结果或 None。

        解析 CLI 输出中的「描述｜窗口N：...」行，回填到对应 session 的
        ai_task_description 字段；剩余行作为建议文本返回。
        """
        if self._pending_proc is None:
            return None

        ret = self._pending_proc.poll()
        if ret is None:
            # 还在跑，检查超时
            if time.time() - self._pending_start > 30:
                self._cancel_pending()
            return None

        # 子进程结束
        stdout = self._pending_proc.stdout.read()
        self._pending_proc = None
        if ret != 0 or not stdout.strip():
            return None

        # 解析：分离描述行和建议行
        desc_lines = {}  # 窗口编号(1-based) -> 描述文本
        advice_lines = []
        for line in stdout.strip().split("\n"):
            stripped = line.strip()
            if stripped.startswith("描述｜窗口"):
                # "描述｜窗口1：查看并修复bug" → key=1, val="查看并修复bug"
                rest = stripped[len("描述｜窗口"):]
                sep = rest.find("：")
                if sep < 0:
                    sep = rest.find(":")
                if sep > 0:
                    try:
                        idx = int(rest[:sep])
                        desc_lines[idx] = rest[sep + 1:].strip()
                    except ValueError:
                        pass
            else:
                advice_lines.append(line)

        # 回填 AI 描述到 sessions
        target = sessions if sessions else self._pending_sessions
        if desc_lines and target:
            for i, s in enumerate(target, 1):
                if i in desc_lines:
                    s.ai_task_description = desc_lines[i]

        return "\n".join(advice_lines).strip() or None

    def _cancel_pending(self):
        """取消进行中的 CLI 调用。"""
        if self._pending_proc is not None:
            try:
                self._pending_proc.kill()
                self._pending_proc.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                pass
            self._pending_proc = None

    def _build_status(self, sessions):
        """构建当前状态文本，每个 session 带编号标签。"""
        blocks = []
        for i, s in enumerate(sessions, 1):
            wait_min = int(s.wait_seconds / 60) if s.wait_seconds else 0
            # 阶段判断
            if s.is_completed:
                phase = "已完成"
            elif s.has_error:
                phase = f"出错：{s.error_message}" if s.error_message else "出错"
            else:
                phase = "执行中"

            cli_name = "Claude Code" if s.cli_type == "claude" else "Codex"
            ws = os.path.basename(s.workspace) if s.workspace else "未知"
            task = s.task_summary or "未知任务"
            files = ", ".join(os.path.basename(f) for f in s.files_involved[-5:]) if s.files_involved else "无"

            block = (
                f"【窗口{i}：{cli_name} · {ws}】\n"
                f"- 任务：{task}\n"
                f"- 阶段：{phase}\n"
                f"- 已等待：{wait_min} 分钟\n"
                f"- 涉及文件：{files}"
            )
            blocks.append(block)
        return "\n\n".join(blocks)

    def _build_prompt(self, status_block, n_sessions):
        """构建完整 prompt。"""
        waitdex = self._waitdex_sections
        common_rules = (
            "你是一个轻松随意的等待期小助手。\n\n"
            "## 面板结构（你必须理解这个上下文）\n"
            "面板分上下两区：\n"
            "- 监控区：状态图标 + CLI名 + 项目名 + 任务描述 + 状态词 + 时长\n"
            "  任务描述已在监控区显示，建议区不需要重复\n"
            "- 建议区：你的输出显示在这里，只负责关心建议\n\n"
            "## 输出格式（严格遵守）\n"
            "1. 先为每个窗口输出一行任务描述（供监控区回填），格式「描述｜窗口N：裸动作描述」\n"
            "   裸动作描述：10 字以内，用 AI 视角（×「处理用户的bug」→ ○「排查登录异常」）\n"
            "2. 再输出 1-3 条关心建议，格式「· 建议」\n"
            "   建议区不需要包含项目名或任务描述，只需要关心和行动建议\n\n"
            "## 建议示例\n"
            "- 执行中：「· 工作有一会儿了，站起来活动活动吧」\n"
            "- 已完成：「· Trading-Burger 搞定了。喝口水，回来看看 diff」\n"
            "- 有报错：「· Trading-Burger 碰到点问题，不着急，回来看一眼就好」\n\n"
            "## 建议的规则\n"
            "- 任务描述已在监控区，建议区只需关心建议（完成/报错时可带项目名）\n"
            "- 语气温柔体贴，像朋友关心你一样——先照顾人，再说事情\n"
            "- 任何时候建议休息都是合理的，要有铺垫和温度\n"
            "  （×「站起来活动一下」→ ○「工作有一会儿了，站起来活动活动吧」）\n"
            "- 区分会话阶段：\n"
            "  · 已完成：先关心人（喝水、活动），再顺带提 review\n"
            "  · 有报错：温和安抚，不着急，回来看一眼就好\n"
            "  · 执行中：不建议看具体文件（你不知道全局进度），\n"
            "    改为身体恢复、准备下一轮、或轻量维护\n"
            "- 根据等待时长调整：<2分钟偏身体恢复，2-10分钟偏下一轮准备，>10分钟可做轻量闭环任务\n"
        )
        if n_sessions > 1:
            prompt = common_rules + "用户正在同时等多个 AI 编码工具。\n"
        else:
            prompt = common_rules + "用户正在等一个 AI 编码工具跑完。\n"
        if waitdex:
            prompt += f"\n{waitdex}\n"
        prompt += f"\n当前状态：\n{status_block}"
        return prompt

    # WaitDex 风格的体贴建议池——语气温柔，像朋友随口一提
    _TIPS_SHORT = [  # < 2 分钟：身体重置
        "工作有一会儿了，站起来活动活动吧",
        "趁这会儿喝口水，放松一下肩颈",
        "抬头看看远处，让眼睛歇一歇",
        "深呼吸几次，等它跑完咱再看",
        "伸个懒腰，转转脖子，马上就好",
    ]
    _TIPS_MEDIUM = [  # 2-10 分钟：下一轮准备 + 轻维护
        "趁还在跑，想想结果出来先看哪两个文件",
        "去接杯水，回来顺手草拟下一条 prompt",
        "起来走走，回来整理一下 TODO 或临时笔记",
        "列几条验收要点，等会儿对着查就不慌了",
        "还要一会儿呢，站起来活动活动再回来",
    ]
    _TIPS_LONG = [  # > 10 分钟：轻量闭环
        "还早呢，去喝口水看看远方，回来再说",
        "这轮要跑一阵子，回条消息或补一小段文档吧",
        "趁这段空档清理一下浏览器标签，轻松一下",
        "去走动走动，回来整理下 issue 或笔记",
        "读一篇短文章放松放松，它跑完会等你的",
    ]

    def _rule_engine(self, sessions):
        """纯规则引擎兜底，任务描述已在监控区，建议区只输出关心建议。"""
        lines = []
        has_active = False

        for s in sessions:
            ws = os.path.basename(s.workspace) if s.workspace else ""
            recent_file = os.path.basename(s.files_involved[-1]) if s.files_involved else ""
            wait_min = int(s.wait_seconds / 60) if s.wait_seconds else 0

            if s.is_completed:
                if recent_file:
                    lines.append(f"{ws} 搞定了。喝口水，回来看看 {recent_file} 的 diff")
                else:
                    lines.append(f"{ws} 搞定了。起来活动一下，回来跑跑测试就好")
            elif s.has_error:
                lines.append(f"{ws} 碰到点问题，不着急，回来看一眼就好")
            elif wait_min >= 5 and self._is_stale(s):
                lines.append(f"{ws} 好像卡住了，去终端瞅一眼吧")
            else:
                has_active = True

        # 对执行中的会话，从建议池选一条关心建议
        if has_active and len(lines) < 3:
            max_wait = max(
                (int(s.wait_seconds / 60) if s.wait_seconds else 0)
                for s in sessions if not s.is_completed and not s.has_error
            )
            if max_wait < 2:
                pool = self._TIPS_SHORT
            elif max_wait <= 10:
                pool = self._TIPS_MEDIUM
            else:
                pool = self._TIPS_LONG
            tip = random.choice(pool)
            if tip not in lines:
                lines.append(tip)

        # 去重，最多 3 条
        seen = []
        for t in lines:
            if t not in seen:
                seen.append(t)
            if len(seen) >= 3:
                break

        return "\n".join(f"· {t}" for t in seen)

    def _is_stale(self, session):
        """检查文件是否 5 分钟无更新（已完成的会话不算卡住）。"""
        if session.is_completed:
            return False
        try:
            mtime = os.path.getmtime(session.file_path)
            return time.time() - mtime > 300
        except OSError:
            return False

    def _load_waitdex(self):
        """从 WaitDex.md 提取 ## 3. / ## 4. / ## 9. 开头的 section。"""
        try:
            ref = importlib.resources.files("src").joinpath("WaitDex.md")
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
