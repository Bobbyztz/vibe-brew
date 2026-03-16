# Roadmap

## Phase 0 — CLI Demo (Current)

**Goal**: Validate whether "conversation flow monitoring + content understanding + WaitDex suggestions" is a viable approach.

- Modules organized under `src/`, run via `python src/vibe_brew.py` in terminal
- Discover active Claude Code / Codex sessions on the system
- Get conversation content and state via direct JSONL reading
- Get terminal content via AppleScript / tmux as fallback
- Detect state changes, generate suggestions using WaitDex strategy
- Simple TUI display

**Questions answered upon completion**:
- Can direct JSONL reading reliably capture conversation state?
- Do lightweight cloud model + WaitDex context suggestions have real value?
- Are users willing to keep an extra terminal open for this?

## Phase 1 — Desktop Pet

**Key leap**: Users no longer need to dedicate a terminal window.

**Goal**: Transform from tool to companion.

- On-screen character (a simmering pot, an animal, a robot — varies by theme)
- State-driven animations:
  - AI running → pet is stirring soup / watching the fire
  - Session completed → pet raises flag / taps bowl
  - Waiting too long with no activity → pet yawns / reminds you to stand up
- Speech bubble delivers WaitDex suggestions
- Draggable, interactive
- Tech stack: Swift + SpriteKit, or Electron + Lottie

**Key leap**: Emotional connection. It's not just a monitoring panel — it's your vibe coding companion.

## Phase 2 — Community & Ecosystem

**Vision**: Let every vibe coder have their own brew style.

- Pet skins and theme marketplace
- Plugin system: custom monitoring rules, custom suggestion strategies
- More model provider support
- Team mode: see teammates' brew status, know what each other is working on during async collaboration
- Cross-platform: Linux, Windows support (Phase 3+)
- Custom WaitDex strategies: adjust suggestion priorities based on personal habits

Specific form for this phase depends on user feedback from Phases 0-2; implementation details not planned prematurely.
