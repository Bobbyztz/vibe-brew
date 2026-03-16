# Technical Design

## Core Idea

Monitor conversation flows, not process types.

Traditional approaches scan processes via `ps`, categorizing by command name (python, node, cargo...). The problem: a single Claude Code conversation spawns multiple subprocess types, and splitting by type loses their relationship.

vibe-brew's strategy: use AI CLI (Claude Code, Codex) conversation flows as the top-level monitoring unit, getting structured context through direct session file reading, with terminal content capture as fallback.

## Data Flow

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  Data Source Layer│     │  Session Manager  │     │  Advice Generator│
│                  │     │                  │     │                  │
│  ┌─ JSONL read   │     │  Identify sessions│     │  State + WaitDex │
│  │  ~/.claude/   │────▶│  Attribute sub-   │────▶│  + conversation  │
│  │  ~/.codex/    │     │  processes        │     │  → AI model      │
│  │              │     │  Detect changes   │     │  → 1-3 suggestions│
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
                                                  │  Terminal TUI     │
                                                  │  Sessions + Advice│
                                                  └──────────────────┘
```

## Code Structure

Phase 0 organizes files under `src/`, with `python src/vibe_brew.py` as the sole entry point:

```
src/
├── vibe_brew.py          # Entry point, main loop + TUI rendering
├── session_discoverer.py # Session discovery
├── content_reader.py     # JSONL parsing + terminal content capture
├── state_detector.py     # State change detection
└── advisor.py            # Advice generation (AI API / rule engine)
```

Zero external dependencies (stdlib only), AI advice generation via `subprocess` calling installed AI CLI. `src/` is not a Python package, no `__init__.py` needed, modules use direct same-directory imports (e.g. `from session_discoverer import SessionDiscoverer`).

All file I/O uses `encoding='utf-8'`.

## Main Loop

The main loop in `vibe_brew.py` uses simple `time.sleep(5)` polling, pseudocode:

```python
last_api_call_time = 0
last_advice = ""
sessions_state = {}  # session_id -> previous round state snapshot

while True:
    # 1. Discover active sessions
    sessions = discoverer.discover()

    # 2. Read content for each session
    for session in sessions:
        reader.update(session)

    # 3. Detect state changes
    changes = detector.detect(sessions, sessions_state)
    sessions_state = detector.snapshot(sessions)

    # 4. Decide whether to update advice
    now = time.time()
    need_update = (
        changes.has_significant_change()  # State change (completed/error/new session)
        or (now - last_api_call_time >= 60 and sessions)  # 60s periodic refresh
    )

    if need_update:
        last_advice = advisor.generate(sessions)
        last_api_call_time = now

    # 5. Render TUI
    renderer.render(sessions, last_advice)

    time.sleep(5)
```

**Key Timing Parameters**:
- Poll interval: 5 seconds (scan files + render)
- Minimum API call interval: 60 seconds (periodic refresh even without state changes)
- State changes trigger immediate API call and reset the 60s timer
- No active sessions: still polls, but doesn't call API; TUI shows "No active sessions"

## Module Breakdown

### 1. Session Discoverer

Discovers active AI coding sessions on the system.

**Claude Code**:
- Scans `~/.claude/projects/` directory
- Each `<encoded-cwd>/<session-uuid>.jsonl` is a session
- `<encoded-cwd>` encoding: replace `/` in absolute working directory path with `-`, e.g. `/Users/alice/my-project` → `-Users-alice-my-project`
- Active status determined by file modification time (written within last 10 minutes)
- JSONL filename is the session UUID (e.g. `7a587be3-237a-433a-ae6a-201bdbf6bf51.jsonl`)
- Each JSONL record's `cwd` field contains the session's working directory

**Codex CLI**:
- Scans `~/.codex/sessions/` directory
- `YYYY/MM/DD/rollout-<timestamp>-<uuid>.jsonl` is the session log
- Same file modification time check for active status
- `session_meta` record's `payload.cwd` contains the working directory

**Process Assist** (coarse signal only, not used for session identification):
- Use `pgrep -f "claude"` and `pgrep -f "codex"` to confirm AI CLI processes are running
- Active session determination is based on JSONL file modification time (within last 10 minutes), not process-to-JSONL mapping
- Process detection is only used when: no active JSONL files but AI CLI processes exist → trigger terminal content capture fallback

### 2. Content Reader

Extracts structured state information from sessions.

**Direct JSONL Reading** (primary path):
- tail-follow mode monitoring JSONL files for new lines (tracks lines read, only parses new lines each cycle)
- Each line is an independent JSON object

#### Claude Code JSONL Format

Common fields per record:

| Field | Description |
|-------|-------------|
| `type` | Record type, see below |
| `uuid` | Unique ID for this record |
| `parentUuid` | Parent record UUID, forming conversation tree |
| `timestamp` | ISO 8601 timestamp |
| `sessionId` | Session UUID |
| `cwd` | Working directory absolute path |
| `version` | Claude Code version number |

Record types (`type` field):

| type | Meaning | Key extraction points |
|------|---------|----------------------|
| `user` | User message or tool result | `message.content` contains user prompt; `toolUseResult` field indicates tool execution result |
| `assistant` | AI reply | `message.content` is an array, element types below |
| `system` | System event | `subtype: "turn_duration"` + `durationMs` indicates turn end and duration |
| `progress` | Progress event | Hook execution and other intermediate states |
| `last-prompt` | Session's last prompt | `lastPrompt` field |

`assistant` message `message.content` array element types:

| content type | Meaning | Key fields |
|-------------|---------|------------|
| `thinking` | AI thinking process | `thinking` (text, may be empty string during streaming) |
| `text` | AI text reply | `text` |
| `tool_use` | Tool call | `name` (tool name like Read/Edit/Write/Bash/Glob/Grep), `input` (parameter object with `file_path`/`command` etc.) |

Tool execution results come back via `type: "user"` records:
- `message.content` array contains `type: "tool_result"` elements
- `is_error: true` indicates tool execution error
- `tool_use_id` links to the corresponding `tool_use`

**Turn end detection**: A `type: "system"` + `subtype: "turn_duration"` record indicates the current turn has ended.

**Real samples** (Claude Code):

User message:
```json
{"parentUuid":"...","type":"user","message":{"role":"user","content":"Refactor the auth module"},"uuid":"...","timestamp":"2026-03-14T03:50:26.622Z","cwd":"/Users/alice/my-project","sessionId":"7a587be3-...","version":"2.1.76"}
```

AI tool call:
```json
{"parentUuid":"...","type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","id":"toolu_01L8...","name":"Read","input":{"file_path":"/Users/alice/my-project/auth.py"}}]},"uuid":"...","timestamp":"..."}
```

Tool result (with error):
```json
{"parentUuid":"...","type":"user","toolUseResult":"Error: File not found","message":{"role":"user","content":[{"type":"tool_result","content":"Error: File not found","is_error":true,"tool_use_id":"toolu_01L8..."}]},"uuid":"..."}
```

Turn end:
```json
{"parentUuid":"...","type":"system","subtype":"turn_duration","durationMs":143309,"timestamp":"..."}
```

#### Codex JSONL Format

Common fields per record: `timestamp`, `type`, `payload`.

| type | Meaning | Key payload fields |
|------|---------|-------------------|
| `session_meta` | Session metadata (first record) | `id` (session UUID), `cwd` (working directory), `cli_version`, `model_provider`, `source` ("vscode"/"cli") |
| `event_msg` | Event message | `payload.type` subtypes below |
| `response_item` | AI output content | `payload.type` is `message` (text) or `function_call` (tool call) |
| `turn_context` | Turn context | `cwd`, `model`, `turn_id` |

`event_msg` `payload.type` subtypes:

| payload.type | Meaning |
|-------------|---------|
| `task_started` | A turn begins |
| `task_complete` | A turn ends, `last_agent_message` contains completion summary |
| `agent_reasoning` | AI thinking process |
| `agent_message` | AI text message |
| `user_message` | User message |

Tool call (`response_item` + `function_call`):
```json
{"timestamp":"...","type":"response_item","payload":{"type":"function_call","name":"exec_command","arguments":"{\"cmd\":\"cat docs/index.md\"}","call_id":"call_Or5..."}}
```

Tool result (`response_item` + `function_call_output`):
```json
{"timestamp":"...","type":"response_item","payload":{"type":"function_call_output","call_id":"call_Or5...","output":"File content or execution output..."}}
```

Error cases: `output` field contains error info (e.g. `"command exited with code 1: ..."`), detected by checking for `error`, `Error`, `exited with code [non-0]` keywords.

**Turn end detection**: An `event_msg` + `payload.type: "task_complete"` indicates the current turn has ended.

#### State Information Extraction Logic

State information extracted from JSONL records for advice generation:
- **Current action**: Most recent `tool_use` (Claude Code) or `function_call` (Codex) `name` field
- **Involved files**: Collected from `tool_use.input.file_path` (Claude Code) or paths in `function_call.arguments` (Codex)
- **Error status**: Claude Code checks `tool_result.is_error`; Codex checks error messages in `function_call_output`
- **Wait duration**: Current time - most recent `user` record (excluding tool_result) `timestamp`
- **Completion status**: Claude Code checks `system` + `turn_duration`; Codex checks `task_complete`

**Terminal Content Capture** (fallback path):

When JSONL is unavailable (e.g. non-standard AI CLI), captures screen text from terminal.

*Terminal.app*:
```bash
osascript -e 'tell application "Terminal" to get contents of selected tab of front window'
# Or get full scrollback
osascript -e 'tell application "Terminal" to get history of selected tab of front window'
```

*Ghostty (v1.3+)*:
```bash
osascript -e 'tell application "Ghostty" to get contents of current terminal of front window'
```

*tmux*:
```bash
tmux capture-pane -p -S -    # get full scrollback
tmux capture-pane -p -t session:window.pane  # specify pane
```

Terminal matching strategy (Phase 0 simplified):
- Phase 0 only captures the frontmost window's current tab/pane content, no precise PID → TTY → window mapping
- Prefers AppleScript (zero permissions), tmux auto-enabled when tmux environment detected

### 3. State Detector

After each scan cycle (5-second interval), diffs against the previous round's results to detect:

- **New session**: New active JSONL file discovered
- **Session completed**: Claude Code shows `type: "system"` + `subtype: "turn_duration"`; Codex shows `event_msg` + `payload.type: "task_complete"`
- **Error**: Claude Code shows `tool_result.is_error: true`; Codex shows error-containing `function_call_output`
- **Long inactivity**: JSONL file has no new content for over 5 minutes (`os.path.getmtime()` comparison), possibly stuck
- **Phase switch**: Recent tool call name changed (e.g. `Edit` → `Bash`, suggesting "modifying code" → "running tests")

State changes are the primary signal for triggering advice updates.

### 4. Advisor

Generates WaitDex-based wait-time suggestions.

**Call Strategy**:

Since users are vibe coding, they already have AI CLI installed with active subscriptions. vibe-brew calls the installed CLI directly via `subprocess` for advice, requiring no API key configuration.

Priority:
1. **CLI wrapper call** (detect `claude` command available) → `subprocess.run(["claude", "-p", "--no-session-persistence", prompt])`, reusing existing subscription
2. **Pure rule engine fallback** → When CLI unavailable or call fails, match suggestions using WaitDex rules + wait duration

**Ephemeral**: `--no-session-persistence` ensures CLI calls don't write JSONL session files. vibe-brew's advice generation calls won't appear in `~/.claude/projects/`, won't be discovered by its own session discovery, leaving no local records.

**Fallback behavior**: CLI call failure (command not found, timeout, non-zero exit) falls through to rule engine. No retries.

**Rule engine matching logic** (fallback when no model available):

| Condition | Summary template | Tip pool (randomly pick 1-2) |
|-----------|-----------------|------------------------------|
| Task completed | "{cli} finished, changed {n} files" | "Check {recent file} diff first", "Run tests to make sure nothing broke" |
| Has error | "{cli} hit an error: {brief description}" | "Might need you to take a look", "Check the error message before deciding next step" |
| Wait < 2min, no anomaly | "{cli} is {current action}, just started" | "Stand up and stretch", "Grab some water", "Look into the distance, rest your eyes" |
| Wait 2-10min, no anomaly | "{cli} is {current action}, running for {n} min" | "Check {recent file} diff", "Draft your next prompt", "Organize your TODOs" |
| Wait > 10min, no anomaly | "{cli} running for {n} min, might be a big one" | "Reply to a message", "Write a quick doc snippet", "Clean up browser tabs" |
| Wait > 5min, file unchanged | "{cli} seems stuck ({n} min no activity)" | "Might want to check the terminal", "Consider whether to abort and retry" |

**Multi-session handling**:

When multiple active sessions exist, all session states are included in a single prompt's "current status" area, generating global advice in one call. This way the model sees the full picture and can give cross-session suggestions (e.g. "A is still running, go review B's results first").

**Input context**:

Only includes current round's conversation state (optionally plus previous round for context), no full history needed. Keeps prompt short, minimal token usage.

```
You are a friendly, casual wait-time assistant. The user is waiting for AI coding tools to finish.

Based on the status below, provide:
1. One-line summary: what the AI is doing
2. 1-3 suggestions: what the user can do now (specific, casual, pick any one)

Tone like a friend mentioning something offhand, no lists, no explanations.

{WaitDex.md sections ## 3 (most practical framework) + ## 4 (actions by wait duration) + ## 9 (one-page cheat sheet), ~80 lines}

Current status:
{repeat following block for each active session}
- AI tool: {Claude Code / Codex}
- Working directory: {cwd}
- Waiting: {N minutes}
- Current action: {latest tool call, e.g. "Edit auth.py" / "Bash: npm test"}
- Files involved: {file path list}
- Anomaly: {yes/no, brief description}
```

**WaitDex injection**: At runtime, reads full text from project root `WaitDex.md`, splits by `## ` level-2 headings, extracts sections with titles starting with `3.`, `4.`, `9.` and concatenates them into the prompt. WaitDex content is not hardcoded. If `WaitDex.md` doesn't exist or can't be read, injection is skipped — the model can still give general advice based on its own knowledge.

**Output format and parsing**:

Model output is free text, no JSON structure required. Advisor passes the model's returned text directly to the renderer for display. The prompt already constrains output format (one-line summary + 1-3 suggestions), no extra parsing needed.

**CLI call details**:
- Uses `subprocess.run(["claude", "-p", "--no-session-persistence", prompt], capture_output=True, text=True, timeout=30)`
- `--no-session-persistence` prevents JSONL session file writing, ephemeral by design
- Rate limiting: minimum 60-second interval, state changes trigger immediate call
- Timeout protection: 30 seconds
- Token usage: < 500 tokens per call, negligible cost
- CLI availability check: `shutil.which("claude")` at startup, if unavailable use rule engine directly

### 5. Renderer

Uses ANSI escape codes for terminal TUI, running in alternate screen buffer (`\033[?1049h` to enter, `\033[?1049l` to exit), each refresh uses cursor home (`\033[H`) + line-by-line overwrite to avoid flickering.

Display content (minimalist, following README.md preview layout):
- Top title bar: `vibe-brew`, drawn with box-drawing characters (`╔═╗╚═╝║`)
- One row per session: status icon (`⟳` running / `●` completed / `⚠` error) + CLI name + workspace last path segment + duration, next line indented with one-line status
- Separator followed by 1-3 suggestions, each starting with `·`
- Entire interface scannable in under 3 seconds
- Width adapts to terminal width (`os.get_terminal_size()`), minimum 40 columns
- Refresh interval: 5 seconds
- `signal.signal(signal.SIGINT, handler)` catches Ctrl+C, handler restores terminal state (`\033[?1049l` to exit alternate screen buffer) before exiting

## Key Design Decisions

### Why Read JSONL Directly Instead of Just Terminal Screen?

| Approach | Pros | Cons |
|----------|------|------|
| Direct JSONL | Structured data, complete info (tool calls, file paths, thinking process) | Limited to supported AI CLIs |
| Terminal screen | Universal, works with any CLI | Plain text, needs parsing, incomplete info |

JSONL is the primary path because its information quality far exceeds screen text — we don't just know "something is running", we know "Claude is using the Edit tool to modify auth.py line 42."

### Why Terminal Content Capture as Fallback?

- Users may use AI CLIs that don't write JSONL
- Some state info only appears in terminal output (e.g. build progress, test results)
- AppleScript works with zero permissions, low implementation cost

### Why Call AI CLI Directly Instead of API Key or Local Model?

| Approach | Pros | Cons |
|----------|------|------|
| API key direct call | Precise model control | Requires user to configure key, raises usage barrier |
| Local model (Ollama) | Offline, zero cost | Requires extra installation, small model advice quality is poor |
| **CLI wrapper call** | **Zero config, reuses existing subscription, high advice quality** | **Requires CLI installed** |

Since users are vibe coding, they already have AI CLI installed. `claude -p --no-session-persistence` — one command generates advice, no API key needed, and `--no-session-persistence` naturally implements ephemeral calls. Privacy-wise, vibe-brew only sends conversation state summaries, not raw code.

When CLI is unavailable (not installed, offline, etc.), falls back to pure rule engine.

### Why 5-Second Polling?

macOS doesn't have a lightweight process/file change event notification mechanism suitable for this scenario. File modification time check + JSONL line count comparison at 5-second intervals has negligible overhead. FSEvents optimization can be considered later.

## Known Limitations

- **JSONL format depends on AI CLI version**: Claude Code / Codex JSONL formats are not guaranteed stable, version upgrades may require adaptation
- **Ghostty AppleScript is a preview feature**: API may change in future versions
- **Terminal screen text needs parsing**: Extracting structured info from plain text has some error margin
- **CLI calls require network**: Falls back to rule engine when offline

## Future Enhancement Directions

- FSEvents to replace polling, reducing resource usage
- Support more AI CLIs (Aider, Continue, etc.)
- Integrate `git diff --stat` for code change context
- More AI CLI and provider support (Codex CLI calls, API key direct calls, Ollama local models, etc.)
- User-customizable WaitDex strategies and keywords
