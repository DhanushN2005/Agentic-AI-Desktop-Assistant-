import json
import os
import re

from utils.config import Config
from utils.voice_parse import strip_wake


def _list_path():
    base = getattr(Config, "DATA_DIR", None) or os.path.join(os.getcwd(), "data")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "todo_list.json")


def _load():
    try:
        with open(_list_path(), encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def _save(items):
    try:
        with open(_list_path(), "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
    except Exception as e:
        import logging
        logging.debug("[todo:_save] %s", e)


def _extract_items(text):
    # Split on "and", commas, semicolons
    parts = re.split(r",|;|\band\b", text, flags=re.IGNORECASE)
    return [p.strip(" .?!") for p in parts if p.strip(" .?!")]


_LIST_WORDS = r"(?:shopping\s+|grocery\s+|to-?do\s+)?(?:list|todo|to-do|to do)(?:\s+list)?"
_LIST_REF = r"(?:(?:to|on|into|in|from|off)\s+)?(?:my|the|our)?\s*" + _LIST_WORDS
_QUESTION = re.compile(r"^(?:what|whats|what's|show|read|list|tell|how|do i|is there)\b", re.IGNORECASE)
_CLEAR = re.compile(
    r"^(?:please\s+)?(?:(?:clear|empty|wipe)(?:\s+out)?\b|(?:delete|remove)\s+(?:all|everything)\b)",
    re.IGNORECASE,
)
_DONE = re.compile(
    r"^(?:please\s+)?(?:mark\s+(?P<a>.+?)\s+(?:as\s+)?(?:done|complete|completed|finished)|"
    r"(?:i'?m\s+)?(?:done|finished)\s+with\s+(?P<b>.+?))\s*[.!]?$",
    re.IGNORECASE,
)
_REMOVE = re.compile(
    r"^(?:please\s+)?(?:remove|delete|take\s+off|cross\s+off|check\s+off)\s+(?P<t>.+?)"
    r"(?:\s+(?:from|off)\s+(?:my|the|our)?\s*" + _LIST_WORDS + r")?\s*[.!]?$",
    re.IGNORECASE,
)
_ADD = re.compile(
    r"^(?:please\s+|can you\s+|could you\s+)?(?:add|put|include|buy|get)\s+(?P<t>.+?)"
    r"(?:\s+(?:to|on|into|in)\s+(?:my|the|our)?\s*" + _LIST_WORDS + r")?\s*[.!]?$",
    re.IGNORECASE,
)


def _remove_targets(items, targets):
    removed = []
    new_items = list(items)
    for t in targets:
        tl = t.lower()
        match = next((it for it in new_items if it.lower() == tl), None)
        if match is None:
            match = next((it for it in new_items if tl in it.lower()), None)
        if match is not None:
            new_items.remove(match)
            removed.append(match)
    return removed, new_items


def handle_todo(orch, c):
    """Voice to-do / shopping list: add, remove, done, clear, list."""
    orch.send_to_ui("STATE", "PROCESSING")
    text = strip_wake(c)
    cmd = text.lower()

    items = _load()

    # Clear
    if _CLEAR.search(text) and not _QUESTION.search(text):
        _save([])
        orch.speak("Cleared your list.")
        orch.ctx.update(last_response="cleared", query=c)
        return True

    # Done / remove (before list so 'remove eggs from my list' is not a read)
    m = _DONE.search(text)
    verb = "Marked done"
    if m:
        target_text = m.group("a") or m.group("b")
    else:
        m = _REMOVE.search(text)
        verb = "Removed"
        target_text = m.group("t") if m else None
    if target_text:
        removed, new_items = _remove_targets(items, _extract_items(target_text))
        _save(new_items)
        if removed:
            orch.speak(verb + " " + ", ".join(removed) + ".")
        else:
            orch.speak("I couldn't find that item on your list.")
        orch.ctx.update(last_response=", ".join(new_items), query=c)
        return True

    # Add
    m = None if _QUESTION.search(text) else _ADD.search(text)
    if m:
        new = _extract_items(m.group("t"))
        if not new:
            orch.speak("What should I add?")
            return True
        items = items + new
        _save(items)
        orch.speak("Added " + ", ".join(new) + ".")
        orch.ctx.update(last_response=", ".join(items), query=c)
        return True

    # List
    if any(w in cmd for w in ["list", "show", "read", "what's on", "whats on", "my list", "my to do", "my todo", "my to-do"]):
        if not items:
            orch.speak("Your list is empty.")
        else:
            orch.speak("Your list has " + str(len(items)) + " item" + ("s" if len(items) != 1 else "") + ": " + ", ".join(items) + ".")
        orch.ctx.update(last_response=", ".join(items), query=c)
        return True

    orch.speak("Say 'add milk to my list', 'remove eggs', 'list my items', or 'clear my list'.")
    orch.ctx.update(last_response="", query=c)
    return True
