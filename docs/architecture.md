# Architecture

## Module Overview

```
src/
├── vibe_brew.py          # Main entry: main loop + TUI rendering
├── session_discoverer.py # Session discovery: scan active JSONL sessions
├── content_reader.py     # Content reading: parse JSONL → structured state
├── state_detector.py     # State detection: diff between cycles, identify change events
└── advisor.py            # Advice generation: AI CLI + rule engine dual strategy
```

## Call Graph

```
vibe_brew.main()
│
│  Every 2 seconds
│
├─① SessionDiscoverer.discover()
│     Scans ~/.claude/projects/ and ~/.codex/sessions/
│     Returns List[Session]
│
├─② ContentReader.update(session)          ← called for each session
│     Incrementally reads JSONL, populates session state fields
│     (current_action, files_involved, has_error,
│       is_completed, wait_seconds, task_summary, etc.)
│
├─③ StateDetector.detect(sessions, prev_state)
│     Diffs snapshots, returns Changes (new/completed/error/stale/action_changed)
│   StateDetector.snapshot(sessions)
│     Generates current cycle snapshot for next cycle comparison
│
├─④ Advisor.generate(sessions, force)
│     force=True skips rate limiting for immediate generation
│     ├─ Primary: async subprocess call to claude CLI (injecting WaitDex context)
│     └─ Fallback: pure rule engine, selects from tip pools by wait duration
│     Returns advice text or None (no update)
│
└─⑤ Renderer.render(sessions, advice)
      Full-screen TUI output (alternate screen buffer)
```

## Data Flow

```
JSONL Session Files
    │
    ▼
SessionDiscoverer ──▶ Session object list (shell, only path/type/ID)
    │
    ▼
ContentReader ──▶ Session objects (state fields populated)
    │
    ├──▶ StateDetector ──▶ Changes (change events)
    │
    └──▶ Advisor ──▶ Advice text (string)
                          │
                          ▼
                     Renderer ──▶ Terminal TUI
```

## Core Data Structures

### Session (defined in session_discoverer.py)

Shared data carrier across all modules, created by `SessionDiscoverer`, populated by `ContentReader`:

| Field | Type | Description |
|-------|------|-------------|
| `file_path` | str | JSONL file path |
| `cli_type` | str | `"claude"` or `"codex"` |
| `workspace` | str | Working directory |
| `session_id` | str | Unique session identifier |
| `current_action` | str | Currently executing tool call |
| `files_involved` | list | Involved file paths (most recent 10) |
| `has_error` | bool | Whether there's an error |
| `error_message` | str | Error message summary |
| `wait_seconds` | float | Seconds since last user message |
| `is_completed` | bool | Whether current turn is completed |
| `task_summary` | str | Summary of user's latest message (≤20 chars) |
| `recent_messages` | list | Recent conversation messages (3 each for user/assistant) |

### Changes (defined in state_detector.py)

Summary of changes detected in one cycle, containing 5 session_id lists: `new_sessions`, `completed`, `errors`, `stale`, `action_changed`.

## External Dependencies

- **Zero pip dependencies**: Uses only the Python standard library
- **AI CLI**: Calls installed `claude` CLI via `subprocess` for advice generation (optional, falls back to rule engine when unavailable)
- **WaitDex.md**: Strategy reference file in project root, `Advisor` loads sections 3/4/9 at initialization
