# 开发指令

你的任务是基于本项目已有的设计文档，从零完成 vibe-brew Phase 0 的全部开发，使 `python src/vibe_brew.py` 可运行并产出预期效果。

## 约束

- 你不会得到任何人工帮助。没有人会帮你提供 API key、安装软件、下载依赖、解答疑问。你必须完全自主完成。
- 零外部依赖，仅使用 Python 标准库。
- 不要修改任何文档文件（`*.md`）。只产出 `src/` 下的代码。
- 不要创建测试文件、配置文件、`__init__.py` 或任何 `src/` 之外的文件。
- 在虚拟环境中完成所有开发与测试

## 必读文档

开始写代码前，通读以下文档，它们包含你需要的一切设计细节：

1. `CLAUDE.md` — 项目概述与开发约定（你已经看到了）
2. `docs/DESIGN.md` — **最关键**，包含代码结构、模块划分、JSONL 格式规格、主循环伪代码、TUI 渲染规格、Advisor prompt 模板等全部实现细节
3. `docs/PRD.md` — 产品需求，定义了输出标准和反模式
4. `WaitDex.md` — Advisor 模块运行时读取此文件注入 prompt

## 产出文件

严格按 `docs/DESIGN.md` 中的代码结构：

```
src/
├── vibe_brew.py          # 入口，主循环 + TUI 渲染
├── session_discoverer.py # 对话流发现
├── content_reader.py     # JSONL 解析 + 终端内容获取
├── state_detector.py     # 状态变化检测
└── advisor.py            # 建议生成（CLI 调用 + 规则引擎）
```

## 开发顺序

按以下顺序逐模块开发。每完成一个模块，立即用简单方式验证它能独立工作（如 `python -c "from session_discoverer import SessionDiscoverer; ..."`），确认无语法错误和基础逻辑问题后再进入下一个。

### 第 1 步：session_discoverer.py

- 扫描 `~/.claude/projects/` 和 `~/.codex/sessions/` 发现活跃 JSONL 文件
- 活跃 = 最近 10 分钟内有写入（`os.path.getmtime()`）
- 用 `pgrep` 检测 AI CLI 进程作为辅助信号
- 返回 session 列表，每个 session 包含：文件路径、CLI 类型（claude/codex）、workspace 路径、session ID
- `<encoded-cwd>` 编码规则见 `CLAUDE.md`

### 第 2 步：content_reader.py

- tail-follow 模式：记录每个 JSONL 文件已读行数，每轮只解析新增行
- Claude Code JSONL 格式和 Codex JSONL 格式的解析规则见 `docs/DESIGN.md` 的详细规格表
- 从 JSONL 提取：当前动作、涉及文件、是否有错误、等待时长、是否完成
- 终端内容获取兜底：AppleScript（Terminal.app、Ghostty）、tmux capture-pane
- 终端获取仅在无活跃 JSONL 但有 AI CLI 进程时触发

### 第 3 步：state_detector.py

- 输入：当前轮 sessions 列表 + 上一轮状态快照
- 检测：新对话流、对话完成、报错、长时间无变化（>5min）、阶段切换
- 输出：变化摘要对象，供主循环判断是否需要更新建议

### 第 4 步：advisor.py

**这是最核心的模块，仔细阅读 `docs/DESIGN.md` 中"建议生成器"一节的完整规格。**

- 启动时用 `shutil.which("claude")` 检测 CLI 可用性
- CLI 可用时：`subprocess.run(["claude", "-p", "--no-session-persistence", prompt], capture_output=True, text=True, timeout=30)`
- CLI 不可用或调用失败时：fall through 到规则引擎，不重试
- Prompt 构建：运行时从项目根目录读取 `WaitDex.md`，提取 `## 3.`、`## 4.`、`## 9.` 开头的 section 注入 prompt。prompt 模板见 `docs/DESIGN.md`
- 规则引擎匹配逻辑：见 `docs/DESIGN.md` 中的规则表，按条件匹配摘要模板 + 随机选建议
- 模型输出为自由文本，整体传递给渲染器展示，不做解析
- 频率限制：最短 60 秒间隔

### 第 5 步：vibe_brew.py

- 主循环按 `docs/DESIGN.md` 中的伪代码实现
- TUI 渲染：alternate screen buffer（`\033[?1049h/l`）、cursor home（`\033[H`）覆写、box-drawing 标题栏、状态图标、建议区
- `signal.SIGINT` 捕获，退出时恢复终端
- 宽度自适应 `os.get_terminal_size()`
- 无活跃对话流时显示"暂无活跃对话"

### 第 6 步：端到端验证

所有模块完成后，运行 `python src/vibe_brew.py` 验证：
1. 程序启动无报错，进入 alternate screen buffer
2. TUI 正确渲染标题栏和布局
3. 如果当前有活跃的 Claude Code 会话，能发现并显示
4. 如果没有活跃会话，显示"暂无活跃对话"
5. Ctrl+C 能干净退出，恢复终端

## 关键注意事项

- `src/` 不是 package，模块间用 `from session_discoverer import SessionDiscoverer` 直接 import
- 所有文件 I/O 用 `encoding='utf-8'`
- JSONL 每行独立 `json.loads()`，跳过解析失败的行（格式容错）
- `WaitDex.md` 的路径：相对于 `vibe_brew.py` 的父目录（即项目根目录），用 `os.path.dirname(os.path.dirname(os.path.abspath(__file__)))` 获取
- 建议语气随意轻松，像朋友顺嘴一提，不要正式、不要解释原因
- vibe-brew 是 toy，代码保持简单直接，不要过度抽象
