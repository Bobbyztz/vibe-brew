# 架构说明

## 模块总览

```
src/
├── vibe_brew.py          # 主入口：主循环 + TUI 渲染
├── session_discoverer.py # 对话流发现：扫描活跃 JSONL 会话
├── content_reader.py     # 内容读取：解析 JSONL → 结构化状态
├── state_detector.py     # 状态检测：对比前后轮次，识别变化事件
└── advisor.py            # 建议生成：AI CLI + 规则引擎双策略
```

## 调用关系

```
vibe_brew.main()
│
│  每 2 秒一轮
│
├─① SessionDiscoverer.discover()
│     扫描 ~/.claude/projects/ 和 ~/.codex/sessions/
│     返回 List[Session]
│
├─② ContentReader.update(session)          ← 对每个 session 调用
│     增量读取 JSONL，填充 session 状态字段
│     （current_action, files_involved, has_error,
│       is_completed, wait_seconds, task_summary 等）
│
├─③ StateDetector.detect(sessions, prev_state)
│     对比快照，返回 Changes（new/completed/error/stale/action_changed）
│   StateDetector.snapshot(sessions)
│     生成本轮快照，供下轮对比
│
├─④ Advisor.generate(sessions, force)
│     force=True 时跳过限流立即生成
│     ├─ 优先：异步 subprocess 调用 claude CLI（注入 WaitDex 上下文）
│     └─ 兜底：纯规则引擎，按等待时长从建议池选取
│     返回建议文本或 None（表示无更新）
│
└─⑤ Renderer.render(sessions, advice)
      全屏 TUI 输出（alternate screen buffer）
```

## 数据流

```
JSONL 会话文件
    │
    ▼
SessionDiscoverer ──▶ Session 对象列表（空壳，只有路径/类型/ID）
    │
    ▼
ContentReader ──▶ Session 对象（填充状态字段）
    │
    ├──▶ StateDetector ──▶ Changes（变化事件）
    │
    └──▶ Advisor ──▶ 建议文本（字符串）
                          │
                          ▼
                     Renderer ──▶ 终端 TUI
```

## 核心数据结构

### Session（定义在 session_discoverer.py）

所有模块共享的数据载体，由 `SessionDiscoverer` 创建，`ContentReader` 填充：

| 字段 | 类型 | 说明 |
|------|------|------|
| `file_path` | str | JSONL 文件路径 |
| `cli_type` | str | `"claude"` 或 `"codex"` |
| `workspace` | str | 工作目录 |
| `session_id` | str | 会话唯一标识 |
| `current_action` | str | 当前执行的工具调用 |
| `files_involved` | list | 涉及的文件路径（最近 10 个） |
| `has_error` | bool | 是否有报错 |
| `error_message` | str | 错误信息摘要 |
| `wait_seconds` | float | 自最后一条用户消息以来的等待秒数 |
| `is_completed` | bool | 当前轮次是否已完成 |
| `task_summary` | str | 用户最近一条消息的摘要（≤20 字符） |
| `recent_messages` | list | 最近对话消息（user/assistant 各保留 3 条） |

### Changes（定义在 state_detector.py）

一轮检测的变化摘要，包含 5 个 session_id 列表：`new_sessions`、`completed`、`errors`、`stale`、`action_changed`。

## 外部依赖

- **零 pip 依赖**：仅使用 Python 标准库
- **AI CLI**：通过 `subprocess` 调用已安装的 `claude` CLI 生成建议（可选，不可用时规则引擎兜底）
- **WaitDex.md**：项目根目录下的策略参考文件，`Advisor` 初始化时加载其中第 3/4/9 节
