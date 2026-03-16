# CLAUDE.md

## 项目概述

vibe-brew 是一个 AI 编程等待期助手，监控 Claude Code / Codex 等 AI CLI 的对话流，结合 WaitDex 策略框架生成等待期建议。

## 最重要的设计原则

vibe-brew 是一个 toy，不是严肃的生产力工具。它的输出必须让用户扫一眼就能随手 pick 一条建议去做，绝不能增加思想负担。WaitDex 是给模型看的 in-context learning 上下文，不是给用户看的内容。摘要最多三行，建议 1-3 条，语气亲切随和。

## 关键上下文

- 建议策略基于 WaitDex（`WaitDex.md`），作为 in-context learning 来源注入模型 prompt
- 监控粒度是**对话流**（一个 Claude Code session），不是进程类型（python/node 等）
- 数据获取首选 JSONL 会话文件直读，兜底用 AppleScript / tmux 终端内容获取
- Claude Code 会话文件在 `~/.claude/projects/<encoded-cwd>/<session-uuid>.jsonl`
- Codex 会话文件在 `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`
- 建议生成通过 `subprocess` 调用已安装的 AI CLI（`claude -p --no-session-persistence`），复用用户已有订阅额度，CLI 不可用时兜底为纯规则引擎

## 当前阶段

Phase 0 — CLI Demo：`src/` 为 Python package，`vibe-brew` 命令为唯一入口。

## 文档结构

- `README.md` — GitHub 门面
- `docs/PRD.md` — 产品需求
- `docs/DESIGN.md` — 技术设计
- `docs/ROADMAP.md` — 演进路线
- `WaitDex.md` — 建议策略参考源（来自 github.com/johnlui/WaitDex）
- `src/` — 源代码

## 开发约定

- 语言：Python 3.10+
- macOS only（Phase 0-1），跨平台支持计划在 Phase 3+
- 零外部依赖（仅标准库），AI 建议生成通过 `subprocess` 调用已安装的 AI CLI
- `src/` 是 Python package，模块间使用相对 import（如 `from .session_discoverer import SessionDiscoverer`）
- 安装方式：`pipx install git+https://github.com/Bobbyztz/vibe-brew.git` 或本地开发 `uv pip install -e .`
- 所有文件 I/O 统一使用 `encoding='utf-8'`
- 建议生成仅发送对话状态摘要（非原始代码），CLI 不可用时纯规则引擎本地运行
- AI CLI 调用使用 `--no-session-persistence` 确保不写入 JSONL 会话文件（阅后即焚），避免被自身 session discovery 发现
- `<encoded-cwd>` 编码规则：将工作目录绝对路径中的 `/` 替换为 `-`，如 `/Users/zhangtianzong/Downloads/vibe-brew` → `-Users-zhangtianzong-Downloads-vibe-brew`
