# 技术设计

## 核心思路

监控对话流，而非进程类型。

传统方案通过 `ps` 扫描进程，按命令名分类（python、node、cargo……）。这种方式的问题是：一个 Claude Code 对话会同时启动多种子进程，按类型切开后它们之间的关联就丢了。

vibe-brew 的策略是：以 AI CLI（Claude Code、Codex）的对话流为顶层监控单位，通过直读会话文件获取结构化上下文，辅以终端内容获取作为兜底。

## 数据流

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  数据源层         │     │  对话流管理        │     │  建议生成         │
│                  │     │                  │     │                  │
│  ┌─ JSONL 直读   │     │  识别对话流       │     │  状态 + WaitDex  │
│  │  ~/.claude/   │────▶│  归属子进程       │────▶│  + 对话内容       │
│  │  ~/.codex/    │     │  检测状态变化      │     │  → AI 模型        │
│  │              │     │                  │     │  → 1-3 条建议     │
│  ├─ AppleScript  │     │                  │     │                  │
│  │  Terminal.app │────▶│                  │     │                  │
│  │  Ghostty     │     │                  │     │                  │
│  │              │     │                  │     │                  │
│  └─ tmux        │     │                  │     │                  │
│     capture-pane│────▶│                  │     │                  │
└──────────────────┘     └──────────────────┘     └──────────────────┘
                                                          │
                                                          ▼
                                                  ┌──────────────────┐
                                                  │  终端 TUI         │
                                                  │  对话流列表 + 建议 │
                                                  └──────────────────┘
```

## 代码结构

Phase 0 在 `src/` 下按模块组织文件，`python src/vibe_brew.py` 为唯一入口：

```
src/
├── vibe_brew.py          # 入口，主循环 + TUI 渲染
├── session_discoverer.py # 对话流发现
├── content_reader.py     # JSONL 解析 + 终端内容获取
├── state_detector.py     # 状态变化检测
└── advisor.py            # 建议生成（AI API / 规则引擎）
```

零外部依赖（仅标准库），AI 建议生成通过 `subprocess` 调用已安装的 AI CLI。`src/` 不是 Python package，无需 `__init__.py`，模块间使用同目录直接 import（如 `from session_discoverer import SessionDiscoverer`）。

所有文件 I/O 统一使用 `encoding='utf-8'`。

## 主循环

`vibe_brew.py` 的主循环采用 `time.sleep(5)` 的简单轮询，伪代码如下：

```python
last_api_call_time = 0
last_advice = ""
sessions_state = {}  # session_id -> 上一轮状态快照

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
        changes.has_significant_change()  # 有状态变化（完成/报错/新对话流）
        or (now - last_api_call_time >= 60 and sessions)  # 60 秒定时刷新
    )

    if need_update:
        last_advice = advisor.generate(sessions)
        last_api_call_time = now

    # 5. 渲染 TUI
    renderer.render(sessions, last_advice)

    time.sleep(5)
```

**关键时间参数**：
- 轮询间隔：5 秒（扫描文件 + 渲染）
- API 调用最短间隔：60 秒（即使无状态变化也定时刷新）
- 状态变化触发立即调用 API，并重置 60 秒计时器
- 无活跃对话流时仍轮询，但不调用 API，TUI 显示"暂无活跃对话"

## 模块划分

### 1. 对话流发现器 (Session Discoverer)

负责发现系统中正在进行的 AI 编码对话流。

**Claude Code**：
- 扫描 `~/.claude/projects/` 目录
- 每个 `<encoded-cwd>/<session-uuid>.jsonl` 是一个对话流
- `<encoded-cwd>` 编码规则：将工作目录绝对路径中的 `/` 替换为 `-`，例如 `/Users/alice/my-project` → `-Users-alice-my-project`
- 通过文件修改时间判断是否活跃（最近 10 分钟内有写入）
- JSONL 文件名即 session UUID（如 `7a587be3-237a-433a-ae6a-201bdbf6bf51.jsonl`）
- 每条 JSONL 记录的 `cwd` 字段包含该对话流的工作目录

**Codex CLI**：
- 扫描 `~/.codex/sessions/` 目录
- `YYYY/MM/DD/rollout-<timestamp>-<uuid>.jsonl` 是对话记录
- 同样通过文件修改时间判断活跃状态
- `session_meta` 记录的 `payload.cwd` 包含工作目录

**进程辅助**（仅作为粗粒度信号，不参与对话流识别）：
- 用 `pgrep -f "claude"` 和 `pgrep -f "codex"` 确认系统中是否有 AI CLI 进程在运行
- 活跃对话流的判断以 JSONL 文件修改时间为准（最近 10 分钟内有写入），不依赖进程到 JSONL 的映射
- 进程检测仅用于：当无活跃 JSONL 文件但有 AI CLI 进程时，触发终端内容获取兜底路径

### 2. 内容读取器 (Content Reader)

从对话流中提取结构化状态信息。

**JSONL 直读**（首选路径）：
- tail-follow 模式监控 JSONL 文件新增行（记录已读行数，每轮只解析新增行）
- 每行是一个独立的 JSON 对象

#### Claude Code JSONL 格式

每条记录的公共字段：

| 字段 | 说明 |
|------|------|
| `type` | 记录类型，见下方 |
| `uuid` | 该记录的唯一 ID |
| `parentUuid` | 父记录 UUID，构成对话树 |
| `timestamp` | ISO 8601 时间戳 |
| `sessionId` | 会话 UUID |
| `cwd` | 工作目录绝对路径 |
| `version` | Claude Code 版本号 |

记录类型（`type` 字段）：

| type | 含义 | 关键提取点 |
|------|------|-----------|
| `user` | 用户消息或工具返回结果 | `message.content` 含用户 prompt；当 `toolUseResult` 字段存在时表示工具执行结果 |
| `assistant` | AI 回复 | `message.content` 是数组，元素类型见下方 |
| `system` | 系统事件 | `subtype: "turn_duration"` + `durationMs` 表示一轮结束及耗时 |
| `progress` | 进度事件 | hook 执行等中间状态 |
| `last-prompt` | 会话最后一条 prompt | `lastPrompt` 字段 |

`assistant` 消息的 `message.content` 数组中，每个元素的 `type`：

| content type | 含义 | 关键字段 |
|-------------|------|---------|
| `thinking` | AI 思考过程 | `thinking`（文本，可能为空字符串表示 streaming 中） |
| `text` | AI 文本回复 | `text` |
| `tool_use` | 工具调用 | `name`（工具名如 Read/Edit/Write/Bash/Glob/Grep）、`input`（参数对象，含 `file_path`/`command` 等） |

工具执行结果通过 `type: "user"` 记录返回：
- `message.content` 数组含 `type: "tool_result"` 元素
- `is_error: true` 表示工具执行出错
- `tool_use_id` 关联到对应的 `tool_use`

**轮次结束判断**：出现 `type: "system"` + `subtype: "turn_duration"` 记录即表示当前轮结束。

**真实样本**（Claude Code）：

用户消息：
```json
{"parentUuid":"...","type":"user","message":{"role":"user","content":"帮我重构 auth 模块"},"uuid":"...","timestamp":"2026-03-14T03:50:26.622Z","cwd":"/Users/alice/my-project","sessionId":"7a587be3-...","version":"2.1.76"}
```

AI 工具调用：
```json
{"parentUuid":"...","type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","id":"toolu_01L8...","name":"Read","input":{"file_path":"/Users/alice/my-project/auth.py"}}]},"uuid":"...","timestamp":"..."}
```

工具结果（含错误）：
```json
{"parentUuid":"...","type":"user","toolUseResult":"Error: File not found","message":{"role":"user","content":[{"type":"tool_result","content":"Error: File not found","is_error":true,"tool_use_id":"toolu_01L8..."}]},"uuid":"..."}
```

轮次结束：
```json
{"parentUuid":"...","type":"system","subtype":"turn_duration","durationMs":143309,"timestamp":"..."}
```

#### Codex JSONL 格式

每条记录的公共字段：`timestamp`、`type`、`payload`。

| type | 含义 | payload 关键字段 |
|------|------|-----------------|
| `session_meta` | 会话元信息（首条记录） | `id`（会话 UUID）、`cwd`（工作目录）、`cli_version`、`model_provider`、`source`（"vscode"/"cli"） |
| `event_msg` | 事件消息 | `payload.type` 子类型见下方 |
| `response_item` | AI 输出内容 | `payload.type` 为 `message`（文本）或 `function_call`（工具调用） |
| `turn_context` | 轮次上下文 | `cwd`、`model`、`turn_id` |

`event_msg` 的 `payload.type` 子类型：

| payload.type | 含义 |
|-------------|------|
| `task_started` | 一轮执行开始 |
| `task_complete` | 一轮执行结束，`last_agent_message` 含完成摘要 |
| `agent_reasoning` | AI 思考过程 |
| `agent_message` | AI 文本消息 |
| `user_message` | 用户消息 |

工具调用（`response_item` + `function_call`）：
```json
{"timestamp":"...","type":"response_item","payload":{"type":"function_call","name":"exec_command","arguments":"{\"cmd\":\"cat docs/index.md\"}","call_id":"call_Or5..."}}
```

工具执行结果（`response_item` + `function_call_output`）：
```json
{"timestamp":"...","type":"response_item","payload":{"type":"function_call_output","call_id":"call_Or5...","output":"文件内容或执行输出..."}}
```

错误时 `output` 字段包含错误信息（如 `"command exited with code 1: ..."`），通过检查 `output` 中是否包含 `error`、`Error`、`exited with code [非0]` 等关键词判断是否出错。

**轮次结束判断**：出现 `event_msg` + `payload.type: "task_complete"` 即表示当前轮结束。

#### 状态信息提取逻辑

从 JSONL 记录中提取以下状态信息用于建议生成：
- **当前动作**：最近的 `tool_use`（Claude Code）或 `function_call`（Codex）的 `name` 字段
- **涉及文件**：从 `tool_use.input.file_path`（Claude Code）或 `function_call.arguments` 中的路径（Codex）收集
- **是否有错误**：Claude Code 看 `tool_result.is_error`；Codex 看 `function_call_output` 中的错误信息
- **等待时长**：当前时间 - 最近一条 `user` 记录（不含 tool_result）的 `timestamp`
- **是否完成**：Claude Code 看 `system` + `turn_duration`；Codex 看 `task_complete`

**终端内容获取**（兜底路径）：

当 JSONL 不可用时（如使用非标准 AI CLI），通过终端内容获取屏幕文本。

*Terminal.app*：
```bash
osascript -e 'tell application "Terminal" to get contents of selected tab of front window'
# 或获取完整 scrollback
osascript -e 'tell application "Terminal" to get history of selected tab of front window'
```

*Ghostty (v1.3+)*：
```bash
osascript -e 'tell application "Ghostty" to get contents of current terminal of front window'
```

*tmux*：
```bash
tmux capture-pane -p -S -    # 获取完整 scrollback
tmux capture-pane -p -t session:window.pane  # 指定 pane
```

终端匹配策略（Phase 0 简化）：
- Phase 0 只获取前台窗口当前 tab/pane 的内容，不做 PID → TTY → 窗口的精确关联
- 优先使用 AppleScript（零权限），tmux 在检测到 tmux 环境时自动启用

### 3. 状态变化检测器 (State Detector)

每轮扫描（5 秒间隔）后，与上一轮结果做 diff，检测：

- **新对话流**：发现新的活跃 JSONL 文件
- **对话完成**：Claude Code 出现 `type: "system"` + `subtype: "turn_duration"`；Codex 出现 `event_msg` + `payload.type: "task_complete"`
- **报错**：Claude Code 出现 `tool_result.is_error: true`；Codex 出现包含错误信息的 `function_call_output`
- **长时间无变化**：JSONL 文件超过 5 分钟没有新增内容（`os.path.getmtime()` 比对），可能卡住
- **阶段切换**：最近的工具调用名称变化（如从 `Edit` 切到 `Bash`，暗示从"修改代码"切到"运行测试"）

状态变化是触发模型建议更新的主要信号。

### 4. 建议生成器 (Advisor)

生成基于 WaitDex 策略的等待期建议。

**调用策略**：

用户既然在 vibe coding，就已经安装了 AI CLI 并有有效订阅。vibe-brew 直接通过 `subprocess` 调用已安装的 CLI 生成建议，无需用户配置任何 API key。

优先级：
1. **CLI 包装调用**（检测 `claude` 命令可用）→ `subprocess.run(["claude", "-p", "--no-session-persistence", prompt])`，复用用户已有订阅额度
2. **纯规则引擎兜底** → CLI 不可用或调用失败时，基于 WaitDex 规则 + 等待时长直接匹配建议

**阅后即焚**：`--no-session-persistence` 确保 CLI 调用不写入 JSONL 会话文件。vibe-brew 的建议生成调用不会出现在 `~/.claude/projects/` 中，不会被自身的 session discovery 发现，不留任何本地记录。

**Fallback 行为**：CLI 调用失败（命令不存在、超时、非零退出码）时，直接 fall through 到规则引擎。不做重试。

**规则引擎匹配逻辑**（无模型可用时的兜底策略）：

| 条件 | 摘要模板 | 建议池（随机选 1-2 条） |
|------|---------|----------------------|
| 任务完成 | "{cli} 已完成，改了 {n} 个文件" | "先看 {最近文件} 的 diff"、"跑一遍测试确认没挂" |
| 有报错 | "{cli} 遇到错误：{错误简述}" | "可能需要你介入看一眼"、"检查一下报错信息再决定下一步" |
| 等待 < 2min，无异常 | "{cli} 正在 {当前动作}，刚开始" | "站起来活动一下"、"喝口水"、"看看远处让眼睛休息" |
| 等待 2-10min，无异常 | "{cli} 正在 {当前动作}，已跑 {n} 分钟" | "看看 {最近文件} 的 diff"、"顺手写下一条 prompt"、"整理一下 TODO" |
| 等待 > 10min，无异常 | "{cli} 已跑 {n} 分钟，可能是个大活" | "回条消息"、"补一小段文档"、"清理一下浏览器标签页" |
| 等待 > 5min 且文件无更新 | "{cli} 好像卡住了（{n} 分钟没动静）" | "可能需要你看一眼终端"、"考虑是不是要中断重试" |

**多对话流处理**：

当系统中存在多个活跃对话流时，将所有对话流的状态拼入同一个 prompt 的"当前状态"区域，一次调用生成全局建议。这样模型能看到全局信息，给出跨对话流的建议（如"A 还在跑，先去 review B 的结果"）。

**输入上下文**：

只塞当前轮次的对话状态（可选加上一轮增强可理解性），不需要完整历史。保持 prompt 短小，token 消耗最低。

```
你是一个轻松随意的等待期小助手。用户正在等 AI 编码工具跑完。

根据下面的状态，给出：
1. 一句话摘要：AI 在干嘛
2. 1-3 条建议：用户现在可以干嘛（要具体、要轻松、随便挑一条就行）

语气像朋友顺嘴一提，不要列清单，不要解释原因。

{WaitDex.md 的 ## 3（最实用的判断框架）+ ## 4（按等待时长选动作）+ ## 9（一页版速查表）的完整内容，约 80 行}

当前状态：
{对每个活跃对话流重复以下块}
- AI 工具：{Claude Code / Codex}
- 工作目录：{cwd}
- 已等待：{N 分钟}
- 当前动作：{最近的工具调用，如 "Edit auth.py" / "Bash: npm test"}
- 涉及文件：{文件路径列表}
- 异常：{有/无，简述}
```

**WaitDex 注入方式**：运行时从项目根目录的 `WaitDex.md` 文件读取全文，按 `## ` 二级标题切割为若干 section，提取标题以 `3.`、`4.`、`9.` 开头的 section 内容拼接后注入 prompt。不硬编码 WaitDex 内容。如果 `WaitDex.md` 文件不存在或读取失败，跳过注入，prompt 中不包含 WaitDex 上下文（模型仍可基于自身知识给出通用建议）。

**输出格式与解析**：

模型输出为自由文本，不要求 JSON 结构。advisor 将模型返回的文本整体作为建议内容传递给渲染器直接展示。Prompt 已约束输出格式（一句话摘要 + 1-3 条建议），无需额外解析。

**CLI 调用细节**：
- 使用 `subprocess.run(["claude", "-p", "--no-session-persistence", prompt], capture_output=True, text=True, timeout=30)` 调用
- `--no-session-persistence` 阻止写入 JSONL 会话文件，实现阅后即焚
- 频率限制：最短 60 秒间隔，状态变化时立即触发
- 超时保护：30 秒
- Token 消耗：每次 < 500 tokens，成本可忽略
- CLI 可用性检测：启动时用 `shutil.which("claude")` 检查，不可用则直接使用规则引擎

### 5. 终端渲染器 (Renderer)

使用 ANSI 转义码实现终端 TUI，运行在 alternate screen buffer 中（`\033[?1049h` 进入，`\033[?1049l` 退出），每次刷新用 cursor home（`\033[H`）+ 逐行覆写避免闪烁。

显示内容（极简，参考 README.md 效果示意图的布局）：
- 顶部标题栏：`vibe-brew`，使用 box-drawing 字符（`╔═╗╚═╝║`）绘制
- 每个对话流一行：状态图标（`⟳` 运行中 / `●` 已完成 / `⚠` 异常）+ CLI 名称 + workspace 最后一段路径 + 时长，下一行缩进显示一句话状态
- 分隔线后显示 1-3 条建议，每条以 `·` 开头
- 整个界面扫一眼 3 秒内能看完
- 宽度自适应终端宽度（`os.get_terminal_size()`），最小 40 列
- 刷新间隔：5 秒
- 使用 `signal.signal(signal.SIGINT, handler)` 捕获 Ctrl+C，在 handler 中恢复原始终端状态（写入 `\033[?1049l` 退出 alternate screen buffer）后退出

## 关键设计决策

### 为什么直读 JSONL 而不只是读终端屏幕？

| 方案 | 优点 | 缺点 |
|------|------|------|
| JSONL 直读 | 结构化数据、信息完整（工具调用、文件路径、思考过程）| 仅限支持的 AI CLI |
| 终端屏幕 | 通用、任何 CLI 都行 | 纯文本、需要解析、信息不完整 |

JSONL 是首选路径，因为它给出的信息质量远高于屏幕文本——我们不只是知道"有进程在跑"，而是知道"Claude 正在用 Edit 工具修改 auth.py 的第 42 行"。

### 为什么需要终端内容获取作为兜底？

- 用户可能使用不写 JSONL 的 AI CLI
- 某些状态信息只出现在终端输出中（如构建进度、测试结果）
- AppleScript 零权限即可工作，实现成本低

### 为什么直接调用 AI CLI 而非 API key 或本地模型？

| 方案 | 优点 | 缺点 |
|------|------|------|
| API key 直调 | 可精确控制模型 | 需要用户额外配置 key，增加使用门槛 |
| 本地模型（Ollama） | 离线、零费用 | 需要额外安装，小模型建议质量差 |
| **CLI 包装调用** | **零配置、复用已有订阅、建议质量高** | **需要 CLI 已安装** |

用户既然在 vibe coding，就已经安装了 AI CLI。`claude -p --no-session-persistence` 一行命令就能生成建议，无需配置任何 API key，且 `--no-session-persistence` 天然实现阅后即焚。隐私方面，vibe-brew 只发送对话状态摘要，不发送原始代码。

CLI 不可用时（未安装、离线等），兜底到纯规则引擎。

### 为什么 5 秒轮询？

macOS 没有轻量的进程/文件变化事件通知机制适合此场景。文件修改时间检查 + JSONL 行数比对在 5 秒间隔下开销可忽略。后续可考虑 FSEvents 优化。

## 已知局限

- **JSONL 格式依赖 AI CLI 版本**：Claude Code / Codex 的 JSONL 格式未承诺稳定，版本升级可能需要适配
- **Ghostty AppleScript 是 preview feature**：API 可能在未来版本变化
- **终端屏幕文本需要解析**：纯文本中提取结构化信息有一定误差
- **CLI 调用需要网络**：离线时回退到规则引擎

## 后续可增强方向

- FSEvents 替代轮询，降低资源占用
- 支持更多 AI CLI（Aider、Continue 等）
- 接入 `git diff --stat` 提供代码变更上下文
- 更多 AI CLI 和 provider 支持（Codex CLI 调用、API key 直调、Ollama 本地模型等）
- 用户自定义 WaitDex 策略和关键词
