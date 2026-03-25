"""Internationalization module (i18n)

Provides language detection and localized string lookup.
Priority: --lang flag > VIBE_BREW_LANG env > system locale > English default.

Only two languages: "zh" and "en". Keeps it simple — no gettext, no frameworks.
"""

import os
import sys

_current_lang = "en"
_auto_mode = False  # True when no explicit source determined the language

# All UI strings, keyed by id
_STRINGS = {
    # TUI chrome
    "no_sessions":      {"en": "No active sessions",    "zh": "\u6ca1\u6709\u6d3b\u8dc3\u7684\u4f1a\u8bdd"},
    "generating":       {"en": "Generating advice...",   "zh": "\u6b63\u5728\u751f\u6210\u5efa\u8bae\u2026\u2026"},
    "exit_hint":        {"en": "Ctrl+C to exit",         "zh": "Ctrl+C \u9000\u51fa"},
    "status_done":      {"en": "Done",                   "zh": "\u5b8c\u6210"},
    "status_running":   {"en": "Running",                "zh": "\u8fd0\u884c\u4e2d"},
    "status_error":     {"en": "Error encountered",      "zh": "\u9047\u5230\u9519\u8bef"},
    "error_with_msg":   {"en": "Error: {err}",           "zh": "\u9519\u8bef\uff1a{err}"},
    "error_with_task":  {"en": "Error \u00b7 {task}",           "zh": "\u9519\u8bef \u00b7 {task}"},
}

# Error templates for TUI status line
_ERROR_TEMPLATES = {
    "en": [
        "Hit a snag while {s}",
        "Ran into an issue with {s}",
    ],
    "zh": [
        "\u5728{s}\u65f6\u9047\u5230\u4e86\u95ee\u9898",
        "{s}\u65f6\u51fa\u4e86\u70b9\u5c0f\u72b6\u51b5",
    ],
}

# Rule-engine tip pools
_TIPS = {
    "en": {
        "short": [
            "You've been at it for a while, stretch your legs!",
            "Take a sip of water and relax your shoulders",
            "Look up at something far away, give your eyes a break",
            "Take a few deep breaths while it runs",
            "Have a good stretch, roll your neck -- almost done",
        ],
        "medium": [
            "While it runs, think about which two files to check first",
            "Grab some water, then draft your next prompt",
            "Take a walk, come back and tidy up your TODOs or notes",
            "Jot down a few acceptance criteria so you're ready when it's done",
            "Still a bit to go -- stand up and move around, then come back",
        ],
        "long": [
            "This'll take a while -- grab some water and look into the distance",
            "Got some time -- reply to a message or write a quick doc snippet",
            "Good time to clean up those browser tabs and decompress",
            "Take a walk, come back and tidy up issues or notes",
            "Read a short article to unwind -- it'll wait for you",
        ],
    },
    "zh": {
        "short": [
            "\u5750\u4e86\u4e00\u4f1a\u513f\u4e86\uff0c\u8d77\u6765\u6d3b\u52a8\u6d3b\u52a8\u5427\uff01",
            "\u559d\u53e3\u6c34\uff0c\u653e\u677e\u4e00\u4e0b\u80a9\u8180",
            "\u62ac\u5934\u770b\u770b\u8fdc\u5904\uff0c\u8ba9\u773c\u775b\u4f11\u606f\u4e00\u4e0b",
            "\u8dd1\u7740\u5462\uff0c\u6df1\u547c\u5438\u51e0\u6b21\u653e\u677e\u4e00\u4e0b",
            "\u4f38\u4f38\u61d2\u8170\uff0c\u8f6c\u8f6c\u8116\u5b50\u2014\u2014\u5feb\u597d\u4e86",
        ],
        "medium": [
            "\u8dd1\u7740\u7684\u65f6\u5019\uff0c\u60f3\u60f3\u7b49\u4f1a\u513f\u5148\u770b\u54ea\u4e24\u4e2a\u6587\u4ef6",
            "\u63a5\u676f\u6c34\uff0c\u987a\u4fbf\u60f3\u60f3\u4e0b\u4e00\u8f6e prompt",
            "\u8d70\u4e00\u8d70\uff0c\u56de\u6765\u6574\u7406\u4e00\u4e0b TODO \u6216\u7b14\u8bb0",
            "\u5148\u5217\u51e0\u6761\u9a8c\u6536\u6807\u51c6\uff0c\u7b49\u4f1a\u513f\u597d\u76f4\u63a5\u4e0a\u624b",
            "\u8fd8\u5f97\u4e00\u4f1a\u513f\u2014\u2014\u8d77\u6765\u8d70\u8d70\uff0c\u56de\u6765\u518d\u770b",
        ],
        "long": [
            "\u8fd9\u8f6e\u8981\u8dd1\u4e00\u4f1a\u513f\u2014\u2014\u63a5\u676f\u6c34\uff0c\u770b\u770b\u8fdc\u5904",
            "\u6709\u70b9\u65f6\u95f4\u2014\u2014\u56de\u4e2a\u6d88\u606f\u6216\u8005\u5199\u6bb5\u5c0f\u6587\u6863",
            "\u597d\u65f6\u673a\u6e05\u7406\u4e00\u4e0b\u6d4f\u89c8\u5668\u6807\u7b7e\u9875\uff0c\u8ba9\u5927\u8111\u900f\u900f\u6c14",
            "\u8d70\u4e00\u8d70\uff0c\u56de\u6765\u6574\u7406 issue \u6216\u7b14\u8bb0",
            "\u770b\u7bc7\u77ed\u6587\u7ae0\u653e\u677e\u4e00\u4e0b\u2014\u2014\u5b83\u4f1a\u7b49\u4f60\u7684",
        ],
    },
}

# Rule-engine status phrases (lists for diversity — pick by session index)
_RULE_STATUS = {
    "done_with_file": {
        "en": [
            "{ws} is done. Grab some water, then check the {f} diff",
            "{ws} finished. Stretch your legs, then review {f}",
            "{ws} wrapped up. Roll your neck, then glance at {f}",
        ],
        "zh": [
            "{ws} \u5b8c\u6210\u4e86\u3002\u559d\u53e3\u6c34\uff0c\u7136\u540e\u770b\u770b {f} \u7684 diff",
            "{ws} \u8dd1\u5b8c\u4e86\u3002\u4f38\u4f38\u61d2\u8170\uff0c\u7136\u540e\u7785\u4e00\u773c {f}",
            "{ws} \u641e\u5b9a\u4e86\u3002\u8f6c\u8f6c\u8116\u5b50\uff0c\u7136\u540e\u68c0\u67e5\u4e00\u4e0b {f}",
        ],
    },
    "done_no_file": {
        "en": [
            "{ws} is done. Stretch a bit, then run the tests",
            "{ws} finished. Grab some water, then check the output",
            "{ws} wrapped up. Take a breath, then review the changes",
        ],
        "zh": [
            "{ws} \u5b8c\u6210\u4e86\u3002\u4f38\u4f38\u61d2\u8170\uff0c\u7136\u540e\u8dd1\u4e0b\u6d4b\u8bd5",
            "{ws} \u8dd1\u5b8c\u4e86\u3002\u559d\u53e3\u6c34\uff0c\u7136\u540e\u770b\u770b\u8f93\u51fa",
            "{ws} \u641e\u5b9a\u4e86\u3002\u6df1\u547c\u5438\uff0c\u7136\u540e review \u4e00\u4e0b\u6539\u52a8",
        ],
    },
    "error": {
        "en": [
            "{ws} hit a snag, no rush -- take a look when you're ready",
            "{ws} ran into something -- stretch first, then check it out",
            "{ws} needs attention -- grab some water and take a look",
        ],
        "zh": [
            "{ws} \u9047\u5230\u4e86\u70b9\u95ee\u9898\uff0c\u4e0d\u6025\u2014\u2014\u6709\u7a7a\u518d\u770b\u770b",
            "{ws} \u78b0\u5230\u70b9\u72b6\u51b5\u2014\u2014\u5148\u6d3b\u52a8\u6d3b\u52a8\uff0c\u518d\u53bb\u770b\u770b",
            "{ws} \u9700\u8981\u6ce8\u610f\u4e00\u4e0b\u2014\u2014\u559d\u53e3\u6c34\uff0c\u7136\u540e\u7785\u7785",
        ],
    },
    "stale": {
        "en": [
            "{ws} seems stuck -- check the terminal when you get a chance",
        ],
        "zh": [
            "{ws} \u597d\u50cf\u5361\u4f4f\u4e86\u2014\u2014\u6709\u7a7a\u770b\u770b\u7ec8\u7aef",
        ],
    },
}


def init_lang(cli_arg=None):
    """Determine language and set module-level state.

    Priority: cli_arg > VIBE_BREW_LANG env > system locale > macOS AppleLocale
    > auto-detect from session content (deferred) > English default.
    """
    global _current_lang, _auto_mode

    lang = None

    # 1. CLI argument
    if cli_arg and cli_arg.lower() in ("zh", "en"):
        lang = cli_arg.lower()

    # 2. Environment variable
    if not lang:
        env = os.environ.get("VIBE_BREW_LANG", "").lower()
        if env in ("zh", "en"):
            lang = env

    # 3. System locale
    if not lang:
        sys_locale = os.environ.get("LC_ALL") or os.environ.get("LANG") or ""
        if sys_locale.lower().startswith("zh"):
            lang = "zh"

    # 4. macOS: many Chinese users have LANG=en_US.UTF-8 in shell but Chinese
    #    system UI. Check AppleLocale as a more reliable signal on macOS.
    if not lang and sys.platform == "darwin":
        try:
            import subprocess
            r = subprocess.run(
                ["defaults", "read", "-g", "AppleLocale"],
                capture_output=True, text=True, timeout=3,
            )
            if r.returncode == 0 and r.stdout.strip().lower().startswith("zh"):
                lang = "zh"
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    # If no explicit source found, enter auto mode: language will be
    # refined from session content once available
    _auto_mode = lang is None
    _current_lang = lang or "en"
    return _current_lang


def detect_from_sessions(sessions):
    """In auto mode, detect language from user messages in active sessions.

    If any user message contains CJK characters, switch to Chinese.
    Returns True if language was changed (caller should reinitialize
    language-dependent components like Advisor).
    """
    global _current_lang, _auto_mode

    if not _auto_mode:
        return False

    for s in sessions:
        for msg in getattr(s, "recent_messages", []):
            if msg.get("role") == "user" and _has_cjk(msg.get("text", "")):
                if _current_lang != "zh":
                    _current_lang = "zh"
                    _auto_mode = False  # lock in once detected
                    return True
                return False
        # Also check task_summary (available earlier than recent_messages)
        if _has_cjk(getattr(s, "task_summary", "")):
            if _current_lang != "zh":
                _current_lang = "zh"
                _auto_mode = False
                return True
            return False

    return False


def _has_cjk(text):
    """Check if text contains CJK Unified Ideographs."""
    return any('\u4e00' <= ch <= '\u9fff' for ch in text)


def get_lang():
    """Return current language code."""
    return _current_lang


def t(key):
    """Look up a UI string by key."""
    entry = _STRINGS.get(key, {})
    return entry.get(_current_lang, entry.get("en", key))


def get_error_templates():
    return _ERROR_TEMPLATES.get(_current_lang, _ERROR_TEMPLATES["en"])


def get_tips(duration):
    """Return tip pool for given duration bucket: 'short', 'medium', or 'long'."""
    lang_tips = _TIPS.get(_current_lang, _TIPS["en"])
    return lang_tips.get(duration, lang_tips["short"])


def get_rule_status(key, index=0, **kwargs):
    """Return a formatted rule-engine status string.

    index selects which template variant to use, so different sessions
    get different action suggestions even when they share the same status.
    """
    entry = _RULE_STATUS.get(key, {})
    templates = entry.get(_current_lang, entry.get("en", []))
    if not templates:
        return ""
    template = templates[index % len(templates)]
    return template.format(**kwargs)
