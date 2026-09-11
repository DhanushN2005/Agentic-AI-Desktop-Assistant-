import os
import re


def handle_file_rename(orch, c):
    orch.speak(orch.files.rename_item(c))
    return True


def handle_file_delete(orch, c):
    target = re.sub(r"(delete|remove|erase|file|folder|the)", "", c).strip()
    if orch.voice.confirm(f"Are you absolutely sure you want to delete '{target}'? This cannot be undone."):
        orch.speak(orch.files.delete_item(c))
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
    if "organize" in c or "clean" in c:
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
        orch.speak(res)
    return True


def handle_knowledge_search(orch, c):
    if "recent" in c:
        orch.speak(orch.knowledge.list_recent_documents())
    else:
        query = re.sub(r"(search my files for|search my files|find in my documents|what do my notes say about)", "", c).strip()
        orch.speak(orch.knowledge.search_my_files(query))
    return True
