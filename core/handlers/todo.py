import json
import os
import re

from utils.config import Config


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
    parts = re.split(r",|;|\band\b", text)
    return [p.strip(" .") for p in parts if p.strip(" .")]


def handle_todo(orch, c):
    """Voice to-do / shopping list: add, remove, list, clear."""
    orch.send_to_ui("STATE", "PROCESSING")
    cmd = c.lower().strip()
    cmd = re.sub(r"^(flexi|flexie|hey flexie|ok flexie)\b", "", cmd).strip()

    items = _load()

    # List
    if any(w in cmd for w in ["list", "show", "read", "what's on", "whats on", "my list", "my to do", "my todo"]):
        if not items:
            orch.speak("Your list is empty.")
        else:
            orch.speak("Your list has " + str(len(items)) + " item" + ("s" if len(items) != 1 else "") + ": " + ", ".join(items) + ".")
        orch.ctx.update(last_response=", ".join(items), query=c)
        return True

    # Clear
    if any(w in cmd for w in ["clear", "empty", "delete all", "remove all"]):
        _save([])
        orch.speak("Cleared your list.")
        orch.ctx.update(last_response="cleared", query=c)
        return True

    # Remove
    m = re.search(r"(?:remove|delete|take off|cross off)\s+(.+)", cmd)
    if m:
        targets = _extract_items(m.group(1))
        removed = []
        new_items = list(items)
        for t in targets:
            for it in list(new_items):
                if t in it.lower() or it.lower() in t:
                    new_items.remove(it)
                    removed.append(it)
        _save(new_items)
        if removed:
            orch.speak("Removed " + ", ".join(removed) + ".")
        else:
            orch.speak("I couldn't find that item on your list.")
        orch.ctx.update(last_response=", ".join(new_items), query=c)
        return True

    # Add
    m = re.search(r"(?:add|put|include|buy|get)\s+(.+?)(?:\s+to (?:my )?(?:list|todo|to do|shopping list))?$", cmd)
    if m:
        raw = m.group(1)
        # strip trailing "to my list" leftovers
        raw = re.sub(r"\s+to (?:my )?(?:list|todo|to do|shopping list)$", "", raw).strip()
        new = _extract_items(raw)
        if not new:
            orch.speak("What should I add?")
            return True
        items = items + new
        _save(items)
        orch.speak("Added " + ", ".join(new) + ".")
        orch.ctx.update(last_response=", ".join(items), query=c)
        return True

    orch.speak("Say 'add milk to my list', 'remove eggs', 'list my items', or 'clear my list'.")
    orch.ctx.update(last_response="", query=c)
    return True
