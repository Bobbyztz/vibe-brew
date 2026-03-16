# Product Requirements Document (PRD)

## 1. Product Positioning

vibe-brew is an AI coding wait-time assistant. It monitors users' active AI coding conversations, understands the real-time state and content of each session, and generates context-aware action suggestions based on the WaitDex wait-time strategy framework.

**In one sentence**: Turn vibe coding wait time from "idle drain" into "recovery and preparation."

## 1.1 Most Important Design Principle: Don't Add Burden

vibe-brew is a toy, not a serious productivity tool.

Its entire interaction is: user glances, casually picks one suggestion, then goes and does it. No long texts to read, no decisions to ponder, no buttons to operate.

**Anti-pattern**: Showing the full WaitDex.md content to users, making them read through it each time and think about what to do — this is exactly what vibe-brew aims to eliminate. WaitDex is context for the model, not UI for the user.

**Output Standards**:
- Summary: at most three lines, clearly stating what the AI is doing and how far along
- Suggestions: 1-3 items, just pick any one — no need to do them all
- Tone: casual, relaxed, like a friend mentioning something offhand, not a system issuing commands

## 2. Target Users

Programmers using Claude Code, Codex, and other AI CLI tools for daily development. They:

- Collaborate with AI multiple rounds per day, accumulating 1-2 hours of wait time
- Tend to fall into low-efficiency patterns of scrolling phone or staring at logs during waits
- Want a lightweight tool to manage wait time without changing their existing workflow
- Use macOS, with Terminal.app, Ghostty, or tmux

## 3. Core Scenarios

### Scenario A: Single Session Wait

User is running Claude Code in one terminal, AI is executing a round of changes (3-5 minutes). vibe-brew detects this conversation, reads its state (which files are being modified, which tools are running), and suggests: "Claude is running tests, probably 2 more minutes — grab some water; check the auth.py diff when you're back."

### Scenario B: Parallel Sessions

User has two Claude Code sessions open simultaneously (different workspaces), one refactoring, one just finished. vibe-brew monitors both, suggesting: "Workspace A's refactoring is still running, go review workspace B's API changes first."

### Scenario C: Task Completion Notification

A long-running session suddenly completes. vibe-brew detects the state change and immediately updates: "Codex is done, changed 5 files, all tests passed. Check routes.py first, then test coverage."

### Scenario D: Anomaly Detection

Claude Code gets stuck at a step longer than expected, or encounters an error. vibe-brew prompts: "Claude Code seems stuck on dependency installation (waiting 8 minutes), you might need to check in."

## 4. Core Design Decisions

### 4.1 Monitor by Conversation Flow, Not Process Type

**Wrong model**: Displaying python, node, cargo etc. as independent tasks — they have no relation to each other and create noise.

**Right model**: Use AI CLI conversation flow as the top-level unit, with subprocesses attributed to their corresponding flow.

```
Claude Code (~/project-a, session abc123)    ← conversation flow
  ├── npm test                                ← subtask
  ├── python migrate.py                       ← subtask
  └── cargo build                             ← subtask
```

Conversation flows are identified via:
- Process tree: Claude Code / Codex process is the parent, child processes belong to that flow
- Session files: each JSONL file corresponds to a flow, containing workspace path

### 4.2 Must Access Conversation Content

Just knowing "Claude Code is running" has very low value. Users need to know:
- What the AI is currently doing (modifying files? running tests? installing dependencies?)
- How it's progressing (how many files changed? tests passing?)
- Any anomalies (errors? stuck? waiting for input?)

Acquisition methods (by priority):
1. **Direct JSONL session file reading**: Claude Code writes to `~/.claude/projects/`, Codex writes to `~/.codex/sessions/`, containing complete structured data
2. **Terminal content capture**: AppleScript (Terminal.app, Ghostty) or tmux capture-pane, as fallback

### 4.3 Suggestion Strategy Based on WaitDex

All suggestions follow the WaitDex priority framework:
1. Directly improve next-round output (review goals, draft prompts, list acceptance criteria)
2. Low-brain-cost maintenance (organize TODOs, close tabs)
3. Physical maintenance (stand up, get water, stretch)
4. Light entertainment (must be instantly stoppable)

Dynamically adjusted by wait duration:
- Under 2 minutes → physical reset
- 2-10 minutes → preparation + maintenance
- Over 10 minutes → bounded small tasks

### 4.4 Reuse Existing AI CLI Subscription, Not Local Models

Since users are vibe coding, they already have Claude Code or Codex CLI installed with active subscriptions. vibe-brew calls these installed CLIs directly via `subprocess` to generate advice, requiring no API key configuration.

Strategy:
- **Default**: Call user's installed AI CLI via `subprocess` (`claude -p --no-session-persistence`), reusing existing subscription
- Generating 1-3 suggestions costs very few tokens (< 500 tokens/call), negligible cost
- `--no-session-persistence` ensures advice generation calls don't write JSONL session files, preventing self-discovery by vibe-brew's session discovery — ephemeral by design
- **Fallback**: When CLI is unavailable, match suggestions using WaitDex rules + wait duration (pure rule engine, no external dependencies)

## 5. MVP Feature Scope (Phase 0)

### Must Have

- [ ] Discover and list all Claude Code / Codex sessions on the system
- [ ] Read real-time state and content summaries for each session via JSONL files
- [ ] Get terminal content via AppleScript / tmux as fallback
- [ ] Detect session state changes (new, completed, error, timeout)
- [ ] Feed state + WaitDex strategy to AI CLI (`claude -p --no-session-persistence`) for advice generation, fall back to rule engine when CLI unavailable
- [ ] Terminal TUI displaying session list and suggestions

### Not Now (Later Phases)

- Menu bar app
- Desktop pet
- System notifications
- Multiple AI provider support (API key direct calls, Ollama local models, etc.)
- Plugin system

## 6. Advice Generation Strategy

### Input: As Little As Possible

The model only needs the current round's conversation state (optionally plus previous round for context). No full conversation history needed, no code content.

Prompt context:
1. **Current session state**: What the AI is doing, how long, which files, any anomalies
2. **WaitDex strategy framework**: Injected as in-context learning to guide the model's suggestion direction — this is for the model, not the user

### Output: As Light As Possible

- Summary: at most three lines (what the AI is doing, progress, anomalies)
- Suggestions: 1-3 items, each half a sentence to one sentence
- Tone: casual, conversational, like a friend mentioning something offhand
- Correct usage: glance, pick one, walk away

### Anti-patterns

- ❌ Giving 4+ suggestions for users to choose from — this becomes a decision
- ❌ Writing suggestions formally and completely — this becomes a reading task
- ❌ Listing WaitDex priority framework for users to judge themselves — this becomes a learning task
- ❌ Explaining why for each suggestion — nobody cares, just go get water

## 7. Non-functional Requirements

- **Resource usage**: CPU < 5%, memory < 100MB
- **Response latency**: Update advice within 10 seconds of state change
- **Zero-config startup**: Works with AI CLI environment, no extra installation, no API key config
- **Privacy**: CLI calls only send conversation state summaries (not raw code); pure rule engine runs locally when CLI unavailable
