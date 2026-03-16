# Development Instructions

Your task is to complete all Phase 0 development for vibe-brew from scratch based on the existing design documents, so that `python src/vibe_brew.py` runs and produces the expected results.

## Constraints

- You will not receive any human assistance. No one will help you with API keys, software installation, dependency downloads, or questions. You must complete everything autonomously.
- Zero external dependencies, stdlib only.
- Do not modify any documentation files (`*.md`). Only produce code under `src/`.
- Do not create test files, config files, `__init__.py`, or any files outside `src/`.
- Complete all development and testing in a virtual environment.

## Required Reading

Before writing code, read through the following documents — they contain all the design details you need:

1. `CLAUDE.md` — Project overview and development conventions (you've already seen this)
2. `docs/DESIGN.md` — **Most critical**, contains code structure, module breakdown, JSONL format specs, main loop pseudocode, TUI rendering specs, Advisor prompt templates, and all implementation details
3. `docs/PRD.md` — Product requirements, defines output standards and anti-patterns
4. `WaitDex.md` — Advisor module reads this file at runtime to inject into prompts

## Output Files

Strictly follow the code structure in `docs/DESIGN.md`:

```
src/
├── vibe_brew.py          # Entry point, main loop + TUI rendering
├── session_discoverer.py # Session discovery
├── content_reader.py     # JSONL parsing + terminal content capture
├── state_detector.py     # State change detection
└── advisor.py            # Advice generation (CLI call + rule engine)
```

## Development Order

Develop module by module in the following order. After completing each module, immediately verify it works independently (e.g. `python -c "from session_discoverer import SessionDiscoverer; ..."`), confirm no syntax errors or basic logic issues before moving to the next.

### Step 1: session_discoverer.py

- Scan `~/.claude/projects/` and `~/.codex/sessions/` to discover active JSONL files
- Active = written within last 10 minutes (`os.path.getmtime()`)
- Use `pgrep` to detect AI CLI processes as auxiliary signal
- Return session list, each session containing: file path, CLI type (claude/codex), workspace path, session ID
- `<encoded-cwd>` encoding rules in `CLAUDE.md`

### Step 2: content_reader.py

- tail-follow mode: track lines read per JSONL file, only parse new lines each cycle
- Claude Code and Codex JSONL format parsing rules in `docs/DESIGN.md` spec tables
- Extract from JSONL: current action, involved files, error status, wait duration, completion status
- Terminal content capture fallback: AppleScript (Terminal.app, Ghostty), tmux capture-pane
- Terminal capture only triggered when no active JSONL but AI CLI processes detected

### Step 3: state_detector.py

- Input: current cycle sessions list + previous cycle state snapshot
- Detect: new sessions, completed sessions, errors, long inactivity (>5min), phase switches
- Output: changes summary object for main loop to decide whether to update advice

### Step 4: advisor.py

**This is the most critical module — carefully read the complete "Advisor" section in `docs/DESIGN.md`.**

- Check CLI availability at startup with `shutil.which("claude")`
- When CLI available: `subprocess.run(["claude", "-p", "--no-session-persistence", prompt], capture_output=True, text=True, timeout=30)`
- When CLI unavailable or call fails: fall through to rule engine, no retries
- Prompt construction: read `WaitDex.md` from project root at runtime, extract sections starting with `## 3.`, `## 4.`, `## 9.` and inject into prompt. Prompt template in `docs/DESIGN.md`
- Rule engine matching logic: see rule table in `docs/DESIGN.md`, match summary templates by condition + randomly select suggestions
- Model output is free text, passed directly to renderer, no parsing
- Rate limiting: minimum 60-second interval

### Step 5: vibe_brew.py

- Main loop follows pseudocode in `docs/DESIGN.md`
- TUI rendering: alternate screen buffer (`\033[?1049h/l`), cursor home (`\033[H`) overwrite, box-drawing title bar, status icons, advice area
- `signal.SIGINT` capture, restore terminal on exit
- Width adapts to `os.get_terminal_size()`
- Show "No active sessions" when no active sessions

### Step 6: End-to-End Verification

After all modules are complete, run `python src/vibe_brew.py` to verify:
1. Program starts without errors, enters alternate screen buffer
2. TUI correctly renders title bar and layout
3. If active Claude Code sessions exist, they are discovered and displayed
4. If no active sessions, shows "No active sessions"
5. Ctrl+C exits cleanly, restoring terminal

## Key Notes

- `src/` is not a package, modules use `from session_discoverer import SessionDiscoverer` for direct imports
- All file I/O uses `encoding='utf-8'`
- JSONL is parsed line by line with `json.loads()`, skip lines that fail to parse (format tolerance)
- `WaitDex.md` path: relative to `vibe_brew.py`'s parent directory (project root), use `os.path.dirname(os.path.dirname(os.path.abspath(__file__)))` to get it
- Suggestion tone should be casual and relaxed, like a friend mentioning something offhand, not formal, no explanations
- vibe-brew is a toy, keep code simple and direct, don't over-abstract
