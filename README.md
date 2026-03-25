# vibe-brew ☕ Your cozy companion for AI coding wait times

While you're vibe coding, your brew is simmering.

[中文版](README_CN.md)

## What is vibe-brew

vibe-brew is an AI coding wait-time assistant. It monitors your active AI coding sessions (Claude Code, Codex, etc.), understands the real-time state of each conversation, and generates actionable suggestions based on the [WaitDex](https://github.com/johnlui/WaitDex) wait-time strategy framework.

**The problem it solves**: During vibe coding, each AI round takes 3-10 minutes. You either stare at logs draining your attention, or scroll your phone and shatter your context. Both lose. vibe-brew turns wait time into a window for recovery and preparation.

**What makes it unique**: It doesn't just check "is something running" — it reads the AI CLI's conversation content, knows what Claude Code is doing, which files it changed, whether there are errors, and gives you truly targeted suggestions.

**Design philosophy**: vibe-brew is a toy, not a serious productivity tool. Its output is like a sticky note on your coffee table — glance at it, pick one thing, and go. It should never add to your mental load.

## Preview

```
╔═══════════════════════════════════════════╗
║            📡 vibe-brew                   ║
╚═══════════════════════════════════════════╝

  ⟳ Claude Code  ~/my-project  4m32s
    Refactoring auth module, changed 3 files, 
    running tests

  ● Codex  ~/api-server  0m45s
    Done, waiting for your review

── 💡 ──────────────────────────────────────
  · Grab some water, then check the auth.py diff
  · Codex is done, take a quick look at routes.py
```

## Installation

**Prerequisites**

- macOS
- Python 3.10+
- Claude Code or Codex CLI installed with an active subscription (vibe-brew calls the CLI directly to generate advice — no API key needed)

**For users** — install and use from anywhere:

```bash
uv tool install git+https://github.com/Bobbyztz/vibe-brew.git
```

**For developers** — clone first, then install in editable mode:

```bash
git clone https://github.com/Bobbyztz/vibe-brew.git
cd vibe-brew
uv tool install -e .
```

Both paths give you a global `vibe-brew` command. After installation, run from any directory:

```bash
vibe-brew
```

The developer install (`-e`) means code changes take effect immediately — no reinstall needed.

## How It Works

vibe-brew gets real-time AI coding tool status through two paths:

1. **Direct session file reading** (primary): Both Claude Code and Codex write conversation logs to local JSONL files. vibe-brew tracks these files in real-time to get structured context (what's happening, which tools are called, which files changed).

2. **Terminal content capture** (fallback): Reads terminal screen content via AppleScript (Terminal.app, Ghostty) or `tmux capture-pane`, covering scenarios where JSONL isn't available.

It then calls your installed AI CLI (e.g. `claude -p`) to generate one or two suggestions — a quick glance is all you need. No API key configuration required; it reuses your existing subscription.

## Supported Environments

| AI CLI | Monitoring Method |
|--------|------------------|
| Claude Code | Direct JSONL session file reading |
| Codex CLI | Direct JSONL session file reading |
| Other CLIs | Terminal content capture (AppleScript / tmux) |

| Terminal | Content Capture Method |
|----------|----------------------|
| macOS Terminal.app | AppleScript `contents` / `history` |
| Ghostty (v1.3+) | AppleScript `contents` |
| tmux | `tmux capture-pane` |

## Documentation

- [Product Requirements (PRD)](docs/PRD.md)
- [Technical Design](docs/DESIGN.md)
- [Roadmap](docs/ROADMAP.md)

## Acknowledgments

The wait-time suggestion strategy in this project is based on [WaitDex](https://github.com/johnlui/WaitDex) (by [JohnLui](https://github.com/johnlui)), a systematic AI coding wait-time survival guide. vibe-brew transforms the WaitDex strategy framework from a static document into real-time, context-aware dynamic suggestions.

## License

MIT
