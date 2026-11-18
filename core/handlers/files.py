import os
import re


def handle_file_rename(orch, c):
    orch.speak(orch.files.rename_item(c))
    return True


_NUMBER_WORDS = {"one": 1, "first": 1, "two": 2, "second": 2, "three": 3, "third": 3,
                 "four": 4, "fourth": 4, "five": 5, "fifth": 5, "six": 6, "sixth": 6}


def _choose_candidate(orch, cands):
    """Read the candidates back and wait for a number or a name. Returns a path or None."""
    listing = "; ".join(f"{i + 1}: {os.path.basename(p)}" for i, p in enumerate(cands))
    orch.speak(f"I found {len(cands)} matches. {listing}. Which one? Say the number or the name.")
    try:
        ans = (orch.voice.listen(timeout=8) or "").strip()
    except Exception:
        ans = ""
    if not ans:
        return None
    low = ans.lower()
    m = re.search(r"\b(\d+)\b", low)
    idx = int(m.group(1)) if m else next((n for w, n in _NUMBER_WORDS.items() if re.search(rf"\b{w}\b", low)), 0)
    if 1 <= idx <= len(cands):
        return cands[idx - 1]
    named = [p for p in cands if os.path.basename(p).lower() == low or low in os.path.basename(p).lower()]
    return named[0] if len(named) == 1 else None


def handle_file_delete(orch, c):
    from engines.files import clean_target
    resolver = getattr(orch.files, "resolve_item", None)
    if resolver is None:  # minimal file managers without a resolver
        target = clean_target(c)
        if orch.voice.confirm(f"Are you absolutely sure you want to delete '{target}'?"):
            orch.speak(orch.files.delete_item(c))
        else:
            orch.speak("Deletion cancelled.")
        return True

    path, cands = resolver(c, exact_only=True)  # resolve ONCE
    if not path:
        if not cands:
            orch.speak(f"I couldn't find '{clean_target(c)}' to delete.")
            return True
        path = _choose_candidate(orch, cands)
        if not path:
            orch.speak("I could not tell which one you meant, so nothing was deleted.")
            return True
    if orch.voice.confirm(f"Delete '{path}'? It will be moved to the Recycle Bin."):
        orch.speak(orch.files.delete_path(path))  # delete exactly the confirmed path
    else:
        orch.speak("Deletion cancelled.")
    return True


def handle_file_save(orch, c):
    content = ""
    # Advanced: If it's a 'create about' request OR a code request, use AI to generate content
    if any(x in c for x in ["content of", "about", "code", "script", "py", "program"]):
        query = c
        if "content of" in c:
            query = c.split("content of")[-1].strip()
        elif "about" in c:
            query = c.split("about")[-1].strip()

        orch.speak(f"Researching {query} to save into your document.")
        raw_content = orch.brain.ask(f"Generate the code or summary for: {query}. If it's code, provide ONLY the code.")
        # Strip markdown backticks if present
        content = re.sub(r"```(?:\w+)?\n(.*?)\n```", r"\1", raw_content, flags=re.DOTALL).strip()
        if "```" in content:
            content = content.replace("```", "")  # Final safety strip
    elif orch.ctx.last_response:
        content = orch.ctx.last_response
    elif orch.ctx.last_query:
        content = f"Contextual notes on: {orch.ctx.last_query}"

    # Context chaining: if we just created a folder, save it there
    t_dir = None
    if orch.ctx.last_path and os.path.isdir(orch.ctx.last_path):
        t_dir = orch.ctx.last_path

    res = orch.files.create_document(c, content, target_dir=t_dir)
    if hasattr(orch.files, "last_created_path") and orch.files.last_created_path:
        orch.ctx.update(active_document=orch.files.last_created_path, last_path=orch.files.last_created_path)
    orch.speak(res)
    return True


def handle_file_op(orch, c):
    if "undo" in c and ("organi" in c or "desktop" in c) and hasattr(orch.files, "undo_organize"):
        orch.speak(orch.files.undo_organize())
    elif "organize" in c or "clean" in c:
        orch.speak(orch.files.organize_desktop())
    elif "create" in c or "new folder" in c:
        path = orch.files.create_folder(c)
        orch.ctx.update(last_path=path)
        orch.speak(f"Created folder '{os.path.basename(path)}' at {os.path.dirname(path)}.")
    else:
        # Default to searching and opening
        target = re.sub(r"(find|open|the|folder|app)", "", c).strip()
        res = orch.files.open_item(target)
        if hasattr(orch.files, "last_opened_path") and orch.files.last_opened_path:
            orch.ctx.update(active_document=orch.files.last_opened_path, last_path=orch.files.last_opened_path)
        cands = getattr(orch.files, "last_candidates", None)
        if cands and res.startswith("I found several") and hasattr(orch.files, "open_path"):
            chosen = _choose_candidate(orch, list(cands))
            res = orch.files.open_path(chosen) if chosen else "Okay, I did not open anything."
        orch.speak(res)
    return True


def handle_knowledge_search(orch, c):
    if "recent" in c:
        orch.speak(orch.knowledge.list_recent_documents())
    else:
        query = re.sub(r"(search my files for|search my files|find in my documents|what do my notes say about)", "", c).strip()
        if "what do my notes say about" in c:
            # The user explicitly asked a question about their files: only now may
            # file previews be sent to the LLM.
            orch.speak(orch.knowledge.search_my_files(query, use_llm=True))
        else:
            orch.speak(orch.knowledge.search_my_files(query))
    return True
