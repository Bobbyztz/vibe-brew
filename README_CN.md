# vibe-brew ☕ AI 编程等待期的贴心搭子

Vibe coding 的时候，你的汤在炖着。

## 什么是 vibe-brew

vibe-brew 是一个 AI 编程等待期助手。它监控你正在进行的 AI 编码对话（Claude Code、Codex 等），理解每个对话流的实时状态，然后基于 [WaitDex](https://github.com/johnlui/WaitDex) 的等待期策略框架，给你可操作的建议。

**它解决的问题**：Vibe coding 时，AI 每轮执行需要 3-10 分钟。你要么死盯日志空耗注意力，要么刷手机打散上下文。两种都亏。vibe-brew 帮你把等待期变成恢复和准备的窗口。

**它的独特之处**：不只是看"有没有进程在跑"——它读取 AI CLI 的对话内容，知道 Claude Code 正在干什么、改了哪些文件、有没有报错，然后给出真正有针对性的建议。

**设计原则**：vibe-brew 是一个 toy，不是一个严肃的生产力工具。它的输出就像咖啡桌上的一张便签——扫一眼，随手 pick 一条，然后去做。它绝不应该给你增加思想负担。

## 效果示意

```
╔═══════════════════════════════════════════╗
║            📡 vibe-brew                   ║
╚═══════════════════════════════════════════╝

  ⟳ Claude Code  ~/my-project  4m32s
    重构 auth 模块，改了 3 文件，跑测试中

  ● Codex  ~/api-server  0m45s
    完成，等你 review

── 💡 ──────────────────────────────────────
  · 去接杯水，回来看 auth.py 的 diff
  · Codex 好了，顺手瞄一眼 routes.py
```

## 安装

**前置条件**

- macOS
- Python 3.10+
- Claude Code 或 Codex CLI 已安装并有有效订阅（vibe-brew 直接调用 CLI 生成建议，无需配置 API key）

**用户** — 一键安装，随处可用：

```bash
uv tool install git+https://github.com/Bobbyztz/vibe-brew.git
```

**开发者** — 先 clone，再以 editable 模式安装：

```bash
git clone https://github.com/Bobbyztz/vibe-brew.git
cd vibe-brew
uv tool install -e .
```

两种方式都会得到全局 `vibe-brew` 命令。安装后，在任意目录运行：

```bash
vibe-brew
```

开发者安装（`-e`）意味着改完代码立刻生效，无需重装。

## 工作原理

vibe-brew 通过两条路径获取 AI 编码工具的实时状态：

1. **直读会话文件**（首选）：Claude Code 和 Codex 都会将对话记录写入本地 JSONL 文件，vibe-brew 实时追踪这些文件，获取结构化的上下文信息（当前在做什么、调用了什么工具、改了哪些文件）。

2. **终端内容获取**（兜底）：通过 AppleScript（Terminal.app、Ghostty）或 `tmux capture-pane` 读取终端屏幕内容，覆盖不写入 JSONL 的场景。

然后直接调用你已安装的 AI CLI（如 `claude -p`）生成一条两条建议，扫一眼就够。无需配置 API key，复用你已有的订阅额度。

## 支持的环境

| AI CLI | 监控方式 |
|--------|---------|
| Claude Code | JSONL 会话文件直读 |
| Codex CLI | JSONL 会话文件直读 |
| 其他 CLI | 终端内容获取（AppleScript / tmux） |

| 终端 | 内容获取方式 |
|------|-------------|
| macOS Terminal.app | AppleScript `contents` / `history` |
| Ghostty (v1.3+) | AppleScript `contents` |
| tmux | `tmux capture-pane` |

## 文档

- [产品需求文档 (PRD)](docs/PRD.md)
- [技术设计](docs/DESIGN.md)
- [演进路线](docs/ROADMAP.md)

## 致谢

本项目的等待期建议策略基于 [WaitDex](https://github.com/johnlui/WaitDex)（by [JohnLui](https://github.com/johnlui)），一份系统化的 AI 编程等待期生存指南。vibe-brew 将 WaitDex 的策略框架从静态文档变成实时、上下文感知的动态建议。

## License

MIT
