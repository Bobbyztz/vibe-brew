# CLAUDE.md

## Project Overview

vibe-brew is an AI coding wait-time assistant that monitors Claude Code / Codex and other AI CLI conversation flows, combining the WaitDex strategy framework to generate wait-time suggestions.

## Most Important Design Principle

vibe-brew is a toy, not a serious productivity tool. Its output must let users glance once and casually pick one suggestion to act on — it must never add mental burden. WaitDex is in-context learning context for the model, not content for the user. Summary is at most three lines, 1-3 suggestions, warm and casual tone.

## Key Context

- Suggestion strategy is based on WaitDex (`WaitDex.md`), injected into model prompts as in-context learning source
- Monitoring granularity is **conversation flow** (a Claude Code session), not process type (python/node etc.)
- Data acquisition primarily uses direct JSONL session file reading, with AppleScript / tmux terminal content capture as fallback
- Claude Code session files are at `~/.claude/projects/<encoded-cwd>/<session-uuid>.jsonl`
- Codex session files are at `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`
- Advice generation calls installed AI CLI via `subprocess` (`claude -p --no-session-persistence`), reusing user's existing subscription; falls back to pure rule engine when CLI is unavailable

## Current Phase

Phase 0 — CLI Demo: `src/` is a Python package, `vibe-brew` command is the sole entry point.

## Documentation Structure

- `README.md` — GitHub landing page
- `docs/PRD.md` — Product requirements
- `docs/DESIGN.md` — Technical design
- `docs/ROADMAP.md` — Evolution roadmap
- `WaitDex.md` — Suggestion strategy reference (from github.com/johnlui/WaitDex)
- `src/` — Source code

## Development Conventions

- Language: Python 3.10+
- macOS only (Phase 0-1), cross-platform support planned for Phase 3+
- Zero external dependencies (stdlib only), AI advice generation via `subprocess` calling installed AI CLI
- `src/` is a Python package, modules use relative imports (e.g. `from .session_discoverer import SessionDiscoverer`)
- Installation: `pipx install git+https://github.com/Bobbyztz/vibe-brew.git` or local dev `uv pip install -e .`
- All file I/O uses `encoding='utf-8'`
- Advice generation only sends conversation state summaries (not raw code); pure rule engine runs locally when CLI unavailable
- AI CLI calls use `--no-session-persistence` to ensure no JSONL session files are written (ephemeral), preventing self-discovery by session discovery
- `<encoded-cwd>` encoding rule: replace `/` in the absolute working directory path with `-`, e.g. `/Users/zhangtianzong/Downloads/vibe-brew` → `-Users-zhangtianzong-Downloads-vibe-brew`
