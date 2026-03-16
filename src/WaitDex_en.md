# How to Kill Time While Waiting for Codex / Claude Code

> Source: https://github.com/johnlui/WaitDex

### AKA — The AI Coding Tool Wait-Time Survival Guide

When agent-based coding tools like Codex or Claude Code start modifying code, running tests, checking dependencies, or refactoring projects, developers repeatedly encounter a new work state: **interruptible, unpredictable 3-to-10-minute gaps**.

Handle these well, and they become windows for physical recovery, next-round preparation, and knocking out small tasks. Handle them poorly, and you'll end up doom-scrolling, staring at logs, or starting new rabbit holes — scattering your attention and context.

This document has one simple goal: **help you do the right things during AI wait times, protect your flow, reduce context-switching costs, and make the next collaboration round smoother.**

## 1. The Core Insight: Gap Management Is Not About "Filling Time"

The most common mistake during AI coding waits isn't "wasting a few minutes" — it's **introducing higher cognitive costs just to avoid being idle**. What's truly expensive for developers isn't the wait itself, but these consequences:

- Switching to social media or feeds, then needing to reload your code context when you return
- Staring at the terminal and scrolling logs, turning 5 minutes into 20
- Starting another heavy dev task during the gap, only to be yanked away when the AI returns
- Watching the process without preparing for the next round of review, follow-up, and acceptance

So the first principle of wait-time management isn't "find something to do" — it's:

**Prioritize activities with high payoff, low interruption cost, and that can be stopped instantly.**

Filter every candidate activity through three criteria:

- **Zero context loading**: Don't introduce new information you need to keep tracking
- **Instantly interruptible**: When the AI finishes, you can stop immediately — no "let me just finish this"
- **Real recovery or output**: Either restores your body and attention, or directly improves next-round collaboration quality

## 2. Why This Matters: Developers' Worst Enemy Isn't Waiting — It's Context Loss

Programming is inherently a high working-memory task. You're simultaneously maintaining requirements, edge cases, current implementation, adjacent modules, test risks, and the intent behind your last AI instruction. Once this context gets scattered, recovery is expensive.

During AI waits, the two most dangerous forms of self-interruption are:

- **High-stimulus input**: Social media, short videos, chat messages, infinite feeds
- **High-context tasks**: Another dev task, deep technical reading, problems requiring sustained focus

They share the same problem: you think you're "just glancing," but your brain actually switches task models. When the AI returns, you're not "continuing work" — you're "re-entering work."

So wait-time management is really solving three problems:

1. **Protect flow**: Don't wash away your current code context
2. **Reduce anxiety**: Don't keep refreshing and switching randomly because you're unsure how long the wait will be
3. **Prepare for next steps**: Be ready to review, follow up, and accept the moment results arrive

## 3. The Most Practical Framework: Sort by "Payoff / Interruption Cost"

If you don't want to memorize a bunch of techniques, just remember this priority order.

### 3.1 First Priority: Things That Directly Improve Next-Round Output

This is the most valuable wait-time activity — it introduces almost no new context while noticeably improving subsequent quality.

Things you can do:

- Quick glance at this round's goals and constraints
- Draft your next prompt
- Write a short acceptance checklist
- Note uncovered edge cases
- Write down "which two files I'll check first when results come back"

The minimum viable version is just 3 lines:

- Does this round need tests added?
- Which edge cases aren't covered yet?
- How will I follow up next round?

### 3.2 Second Priority: Low-Brain-Drain Maintenance

If the current task isn't suited for more code thinking, do things that **barely consume judgment and can be stopped anytime**:

- Organize TODOs
- Update issue titles
- Close irrelevant tabs
- Archive temporary notes
- Jot down "I need to ask it about this later"

The value of these: **being interrupted costs nothing — any progress is pure gain.**

### 3.3 Third Priority: Human Maintenance

Often the best move isn't to keep staring at the screen, but to do two minutes of human maintenance:

- Stand up
- Get water
- Stretch
- Use the restroom
- Wash your cup
- Look into the distance to rest your eyes

This is the most stable, least-regretted category of wait-time activity, because it directly improves your physical state — and in the AI era, a developer's scarcest resource often isn't CPU, but spine, eyes, and attention.

### 3.4 Fourth Priority: Light Entertainment, but Must Be "Instantly Stoppable"

If you really want to slack off, that's fine, but with one condition: **you can stop immediately and it won't suck you in.**

Relatively safe choices:

- One song
- One round of Sudoku or 2048
- A few light content items
- A very short article

Not recommended:

- Starting a show
- Long videos
- Infinite-scroll feeds
- New tasks requiring 25+ minutes of sustained focus

## 4. Choose Actions by Wait Duration: The Most Reliable Strategy

Wait times are usually unpredictable, so don't aim for precise scheduling. Instead, use **coarse-grained, extensible, interruptible** choices.

### 4.1 Under 2 Minutes: Focus on Physical Reset

The goal isn't "doing stuff" — it's quick recovery.

Recommended:

- Stand up and move
- Drink water
- Take 3 deep breaths
- Look at something 20 feet away for 20 seconds
- Relax your shoulders, neck, and wrists

Not recommended:

- Picking up your phone
- Checking messages
- Opening any new content

### 4.2 2 to 10 Minutes: Focus on "Next-Round Prep + Light Maintenance"

This is the most typical, most comfortable wait window, and the best time to generate real value.

Recommended:

- Scan the diff or files you plan to review
- Pre-write your next prompt
- List test points, edge cases, acceptance criteria
- Update TODOs / issues / scratch notes
- Stand up, get water, do a light stretch

The most important principle for this window:

**Look at results, look at risks, look at next steps — don't stare at the process.**

The only things worth watching:

- Any errors?
- Which files changed?
- Did tests pass?
- Stuck on permissions, dependencies, or network?

Beyond that, there's no need to burn attention on scrolling logs.

### 4.3 Over 10 Minutes: Do Complete but Non-Sunk Small Modules

If you're fairly sure this is a longer wait, you can tackle a **small, well-bounded, self-contained task**.

Recommended:

- Write a short documentation section
- Organize a runbook
- Read a short technical article with brief annotations
- Handle async messages
- Clean up your desktop or browser tabs
- Learn one small, clearly-bounded concept

Even so, starting another heavy coding task is still not recommended. Because once the AI finishes, you'll still have to hard-switch between two high-context tasks.

## 5. The Most Valuable Wait-Time Activity: Preparing Your Brain for Review

After the AI finishes, what you usually need most isn't to immediately start typing — it's to make judgments.

So the most valuable thing to prepare during the gap isn't "what else can I do" — it's:

- Where is the biggest risk in this change?
- Which two files do I want to check first?
- Which edge cases are most likely missed?
- If the output is wrong, what's my follow-up question?
- If I need to rollback, how do I minimize impact?

This directly changes your AI collaboration quality. Because the key to high-quality collaboration isn't just the prompt — it's **your review capability after output.**

## 6. A Simple Enough Wait-Time Protocol

If you want to make this a stable habit, just follow this sequence.

### 6.1 After the AI Starts Executing

Make a 10-second judgment:

- Is this a short wait or a long wait?
- Do I need physical recovery more, or next-round preparation?

### 6.2 Default Actions

If nothing specific comes to mind, execute this default combo:

1. Stand up for 1 minute
2. Drink water or stretch
3. Come back, scan the diff / target files
4. Write down your next prompt or 3 acceptance criteria

This combo covers recovery, context warmth, and next-step preparation simultaneously — and can be stopped anytime.

### 6.3 After the AI Returns Results

Don't immediately dive into logs or details. Check in order:

1. Any errors or blockers?
2. Which files changed?
3. Did tests pass?
4. Does it match the original goal?
5. Anything needing follow-up, patching, or rollback?

This prevents process noise from leading you around, prioritizing the most critical information.

## 7. Explicitly Listed: What NOT to Do

The biggest wait-time mistakes aren't "doing nothing" — they're doing the wrong things.

The two most discouraged categories:

### 7.1 Staring at the Terminal and Scrolling Logs

This continuously drains attention while rarely providing more control. You'll feel like you're "staying on top of it," but you're really just turning recoverable time into an anxiety amplifier.

### 7.2 Starting Another Heavy Dev Task

This looks efficient but easily creates a violent context collision when the AI returns. The previous task hasn't exited your mind, and the current one demands immediate attention — both end up fragmented.

## 8. Final Advice: Treat AI Waits as "Built-In Recovery Windows"

AI tools bring not just auto-completion, refactoring, and search capabilities — they also introduce fragmented gaps that rarely existed in traditional development workflows. You can think of it as a new work rhythm:

- The machine handles parallel execution
- The human handles judgment, acceptance, trade-offs, and recovery

So the best use of wait time isn't cramming every minute — it's:

- Maintain context with minimal cost
- Recover physically with the shortest actions
- Prepare for the next collaboration round in the most direct way

If you keep only one takeaway from this document:

**During AI waits, prioritize things with high payoff, low interruption cost, and that can be stopped anytime. Physical recovery first, then review preparation, entertainment last.**

## 9. One-Page Cheat Sheet

### Do

- Stand up, drink water, stretch, rest your eyes
- Check the diff, check risks, check acceptance criteria
- Pre-write your next prompt
- Note test points, edge cases, rollback plans
- Organize TODOs, issues, light documentation

### Don't

- Stare at logs
- Scroll infinite feeds
- Start another heavy dev task
- Watch long videos, series, or long-chain entertainment

### Simplest Time Allocation

- **Under 2 minutes**: Stand up + drink water
- **2 to 10 minutes**: Draft next prompt + scan diff
- **Over 10 minutes**: Clear chores + reply messages + patch doc gaps

### Default Recommended Combo

**Stand up for 1 minute, come back and scan the diff, then jot down your next prompt.**

This is usually the highest-payoff, lowest-regret, easiest-to-sustain combo during wait times.

## MIT License

Copyright (c) 2026 JohnLui

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
