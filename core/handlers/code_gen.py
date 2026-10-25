import os
import re
import shutil
import time
import webbrowser
from pathlib import Path

import logging

from utils.config import Config


def _resolve_code_dir(save_path: str) -> str:
    """Resolve a reliable writable directory for generated files."""
    home = Path.home()
    candidates = []
    if save_path:
        requested = Path(save_path).expanduser()
        if requested.is_absolute():
            candidates.append(requested)
        elif any(k in save_path.lower() for k in ("downloads", "download", "my download")):
            candidates = [home / "Downloads", home / "OneDrive" / "Downloads",
                          Path(os.environ.get("USERPROFILE", "")) / "Downloads"]
        elif any(k in save_path.lower() for k in ("desktop", "desktop folder")):
            candidates = [home / "Desktop", home / "OneDrive" / "Desktop"]
    if not candidates:
        candidates.append(Path(Config.CODE_OUTPUT_DIR).expanduser())
    candidates += [home / "Documents", Path(os.getcwd()) / "context" / "created_html"]
    for c in candidates:
        try:
            c.mkdir(parents=True, exist_ok=True)
            if os.access(c, os.W_OK):
                return str(c)
        except Exception:
            continue
    return str(Path(os.getcwd()) / "context" / "created_html")


def _artifact_state(orch):
    getter = getattr(getattr(orch, "ctx", None), "get_artifact", None)
    return getter() if callable(getter) else None


def _read_artifact_source(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            text = handle.read(Config.ARTIFACT_SOURCE_CHARS + 1)
    except OSError:
        return None
    if len(text) > Config.ARTIFACT_SOURCE_CHARS:
        return text[:Config.ARTIFACT_SOURCE_CHARS] + "\n[source truncated for context]"
    return text


def _backup_artifact(path):
    backup_root = Path(Config.ARTIFACT_BACKUP_DIR).expanduser()
    backup_root.mkdir(parents=True, exist_ok=True)
    backup = backup_root / f"{Path(path).name}.{time.time_ns()}.bak"
    shutil.copy2(path, backup)
    return str(backup)


def _write_artifact_file(path, content):
    if os.path.exists(path):
        _backup_artifact(path)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)
    if not os.path.isfile(path):
        return None
    return path


def _explicit_artifact_filename(request, language):
    text = str(request or "").lower()
    extension = _extension_for_language(language)
    for token in re.findall(r"[\w.-]+\.[\w]{1,10}", text):
        if token.endswith(extension):
            return os.path.basename(token)
    named = re.search(r"(?:called|named|as)\s+[\"']?([\w.-]+)", text)
    if named:
        name = named.group(1).strip()
        if not name.endswith(extension):
            name += extension
        return os.path.basename(name)
    return None


def _next_artifact_filename(source_path, language, directory):
    extension = _extension_for_language(language)
    stem = Path(source_path).stem or "generated"
    counter = 2
    while True:
        name = f"{stem}_{counter}{extension}"
        if not os.path.exists(os.path.join(directory, name)):
            return name
        counter += 1


def _extract_change_request(request):
    text = str(request or "").lower().strip()
    text = text.strip(" \t\n\r\"'`.,;")
    text = re.sub(r"^(can|could|will|would|please|do you|would you|can you)\s+(you\s+)?(please\s+)?", "", text)
    text = re.sub(r"^(run|open|launch|start|show|display|preview|execute|test|edit|change|update|modify|revise|fix|improve|enhance|add|insert|append|create|generate|build|make|write|design|develop)\s+", "", text)
    text = re.sub(r"\s+(for me|please)$", "", text)
    text = re.sub(r"^(a|an|the)\s+", "", text)
    text = re.sub(r"\b(that|it|this)\b", " ", text)
    text = re.sub(r"\s+(to|in|on|for|of)\s+(the\s+)?(files?|pages?|documents?|code|apps?|projects?)\s*$", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or str(request or "").strip()


def _connection_requested(request):
    return bool(re.search(r"\b(links?|linked|linking|redirects?|redirecting|navigat\w+|rout\w+|connect\w+|points?|pointing|opens?|opening|loads?|loading|sends?|sending|go|goes|going)\b", str(request or "").lower()))


def _artifact_history(orch, current_query):
    getter = getattr(orch, "get_conversation_history", None)
    history = getter(current_query=current_query, limit=Config.CONVERSATION_HISTORY_TURNS) if callable(getter) else []
    return history or []


def _record_artifact_response(orch, text):
    recorder = getattr(orch, "record_response", None)
    if callable(recorder):
        recorder(text)


def _set_active_artifact(orch, path, language=None, query=None, request=None, related_paths=None):
    setter = getattr(getattr(orch, "ctx", None), "set_artifact", None)
    if callable(setter):
        return setter(path, language=language, query=query, request=request, related_paths=related_paths)
    return None


def _open_artifact_file(orch, artifact, original):
    path = artifact.get("path")
    language = (artifact.get("language") or "").lower()
    if language == "html" or str(path).lower().endswith((".html", ".htm")):
        try:
            webbrowser.open(f"file://{os.path.abspath(path)}")
        except Exception as e:
            logging.debug("[core/handlers/code_gen.py:artifact-open] %s", e)
            orch.speak("I couldn't open the generated file in the browser.", record_chat=False)
            return False
    else:
        result = orch.files.open_item(path)
        if not result or re.search(r"(couldn'?t|could not|failed|error|not found)", result, re.IGNORECASE):
            orch.speak(result or "I couldn't open the generated file.", record_chat=False)
            return False
    orch.ctx.update(last_path=path, active_document=path)
    _set_active_artifact(orch, path)
    _record_artifact_response(orch, f"Opened generated file at {path}.")
    orch.speak(f"Opened {os.path.basename(path)}.", record_chat=False)
    return True


def _edit_active_artifact(orch, artifact, original):
    path = artifact.get("path")
    language = artifact.get("language") or "text"
    source = _read_artifact_source(path)
    if source is None:
        orch.speak("I couldn't read the generated file to update it.", record_chat=False)
        return False
    change = _extract_change_request(original)
    history = _artifact_history(orch, original)
    prompt = "\n".join([
        f"Current request: {original}",
        f"Requested change: {change}",
        f"Active file: {path}",
        f"Current {language} file:",
        f"```{language}",
        source,
        "```",
        "Apply only the requested change to the active file.",
        "Preserve unrelated content, structure, behavior, and formatting.",
        f"Return only the complete updated {language} file.",
    ])
    updated = orch.brain.ask(
        prompt,
        system_override="You are an expert programmer. Update the supplied file and return only the complete updated file. Do not use tools or explain the change.",
        use_rag=False,
        max_tokens=Config.CODE_MAX_TOKENS,
        history=history,
    )
    updated = _clean_code(updated)
    if not updated:
        orch.speak("I couldn't update the generated file.", record_chat=False)
        return False
    if _write_artifact_file(path, updated) is None:
        orch.speak("I ran into a problem saving the updated file.", record_chat=False)
        return False
    orch.ctx.update(last_path=path, last_response=updated, query=change)
    _set_active_artifact(orch, path, language=artifact.get("language"), query=change, request=original)
    _record_artifact_response(orch, f"Updated generated file at {path}.")
    orch.speak(f"Updated {os.path.basename(path)}.", record_chat=False)
    return True


def _link_new_artifact(orch, source_path, target_path, original, history):
    source = _read_artifact_source(source_path)
    if source is None:
        return False
    prompt = "\n".join([
        f"Current request: {original}",
        f"Source file: {source_path}",
        f"New file: {target_path}",
        "Current source file:",
        "```html",
        source,
        "```",
        f"Update the source file so it uses {os.path.basename(target_path)} exactly as requested.",
        "Preserve unrelated content, structure, behavior, and formatting.",
        "Return only the complete updated source file.",
    ])
    updated = orch.brain.ask(
        prompt,
        system_override="You are an expert programmer. Update the supplied source file and return only the complete updated file. Do not use tools or explain the change.",
        use_rag=False,
        max_tokens=Config.CODE_MAX_TOKENS,
        history=history,
    )
    updated = _clean_code(updated)
    if not updated:
        return False
    if _write_artifact_file(source_path, updated) is None:
        return False
    orch.ctx.update(last_path=source_path, last_response=updated)
    return True


def _extend_active_artifact(orch, artifact, original):
    source_path = artifact.get("path")
    source = _read_artifact_source(source_path)
    if source is None:
        orch.speak("I couldn't read the generated file to extend it.", record_chat=False)
        return False
    _, save_hint, language = _parse_code_query(original)
    directory = _resolve_code_dir(save_hint or Config.CODE_OUTPUT_DIR)
    filename = _explicit_artifact_filename(original, language) or _next_artifact_filename(source_path, language, directory)
    target_path = os.path.join(directory, filename)
    history = _artifact_history(orch, original)
    prompt = "\n".join([
        f"Current request: {original}",
        f"Active file: {source_path}",
        f"New file: {target_path}",
        f"Current {artifact.get('language') or language} file:",
        f"```{artifact.get('language') or language}",
        source,
        "```",
        "Create a new file that satisfies the current request.",
        "Use the active file for context, but do not replace it in this response.",
        f"If the new file should refer to the active file, refer to {os.path.basename(source_path)} by filename.",
        "Return only the complete new file.",
    ])
    code = orch.brain.ask(
        prompt,
        system_override="You are an expert programmer. Generate the requested new file and return only its complete code. Do not use tools or explain the change.",
        use_rag=False,
        max_tokens=Config.CODE_MAX_TOKENS,
        history=history,
    )
    code = _clean_code(code)
    if not code:
        orch.speak("I couldn't generate the linked file.", record_chat=False)
        return False
    if _write_artifact_file(target_path, code) is None:
        orch.speak("I ran into a problem saving the linked file.", record_chat=False)
        return False
    orch.ctx.update(last_path=target_path, last_response=code, query=original)
    _set_active_artifact(orch, target_path, language=language, query=original, request=original, related_paths=[source_path])
    _record_artifact_response(orch, f"Generated linked file at {target_path}.")
    linked = False
    if _connection_requested(original) and str(source_path).lower().endswith((".html", ".htm")) and str(target_path).lower().endswith((".html", ".htm")):
        linked = _link_new_artifact(orch, source_path, target_path, original, history)
        if linked:
            _set_active_artifact(orch, target_path, language=language, query=original, request=original, related_paths=[source_path])
    base = os.path.basename(target_path)
    if linked:
        _record_artifact_response(orch, f"Linked {os.path.basename(source_path)} to {base}.")
        orch.speak(f"Created {base} and linked it to {os.path.basename(source_path)}.", record_chat=False)
    else:
        orch.speak(f"Created {base}.", record_chat=False)
    return True


def handle_artifact_command(orch, cmd):
    kind, _, original = cmd.partition(":")
    original = original.strip() or cmd
    artifact = _artifact_state(orch)
    if not artifact:
        try:
            from core.jobs.manager import JobManager
            from core.jobs.models import JobStatus
            mgr = JobManager.get_instance()
            latest = mgr.get_latest_job()
            if latest and latest.status in (JobStatus.FAILED, JobStatus.PAUSED):
                orch.speak(f"Attempting to fix and resume background build for {latest.title}.")
                mgr.resume_job(latest.id)
                return True
        except Exception:
            pass
        orch.speak("I don't have an active generated file for that follow-up yet.", record_chat=False)
        return False
    if kind == "artifact_open" or (kind == "artifact_run" and str(artifact.get("path")).lower().endswith((".html", ".htm"))):
        return _open_artifact_file(orch, artifact, original)
    if kind == "artifact_run":
        return _open_artifact_file(orch, artifact, original)
    if kind == "artifact_edit":
        return _edit_active_artifact(orch, artifact, original)
    if kind == "artifact_extend":
        return _extend_active_artifact(orch, artifact, original)
    orch.speak("I couldn't determine how to continue with the generated file.", record_chat=False)
    return False


def handle_code_gen(orch, c):
    """Generate code based on query, optionally save to file."""
    # Parse query and save location
    query, save_path, language = _parse_code_query(c)

    if not query:
        orch.speak("What code would you like me to generate?", record_chat=False)
        return True

    history_getter = getattr(orch, "get_conversation_history", None)
    history = history_getter(current_query=c, limit=Config.CONVERSATION_HISTORY_TURNS) if callable(history_getter) else []
    history = history or []

    orch.send_to_ui("STATE", "PROCESSING")
    orch.speak(f"Generating {language} code for {query}...", record_chat=False)

    prompt = f"""Generate clean, well-commented {language} code for: {query}

Requirements:
1. Include proper error handling
2. Add clear comments explaining the logic
3. Use best practices and conventions
4. Include a main block or example usage if applicable
5. Make the code production-ready

Return ONLY the code, no explanations outside the code."""

    code = orch.brain.ask(
        prompt,
        system_override="You are an expert programmer. Generate clean, well-commented code. Return ONLY the code. Do not use any tools or functions - just return the raw code text.",
        use_rag=False,
        max_tokens=Config.CODE_MAX_TOKENS,
        history=history,
    )

    if not code:
        orch.speak("I couldn't generate the code. Please try again.", record_chat=False)
        return False

    code = _clean_code(code)

    saved = False
    full_path = None
    if save_path:
        try:
            file_path = _resolve_code_dir(save_path)
            filename = _generate_filename(query, language)
            full_path = os.path.join(file_path, filename)

            if _write_artifact_file(full_path, code) is None:
                orch.speak("I ran into a problem saving the file.", record_chat=False)
                return False

            saved = os.path.isfile(full_path)
            orch.ctx.update(last_path=full_path, last_response=code)
            _set_active_artifact(orch, full_path, language=language, query=query, request=c)
        except Exception as e:
            logging.debug("[core/handlers/code_gen.py:84] Swallowed exception: %s: %s", type(e).__name__, e)
            orch.speak("I ran into a problem saving the file.", record_chat=False)
            return False

    if not saved or not full_path:
        orch.ctx.update(last_response=code, query=query)
        recorder = getattr(orch, "record_response", None)
        if callable(recorder):
            recorder(f"Generated {language} code for {query}.")
        orch.speak("Done. The code is ready.", record_chat=False)
        return True

    base = os.path.basename(full_path)
    recorder = getattr(orch, "record_response", None)
    if callable(recorder):
        recorder(f"Generated {language} code at {full_path}.")
    orch.speak(f"Done, {base} is ready.", record_chat=False)
    if language == "html" and re.search(r"\bopen\b", c.lower()):
        try:
            webbrowser.open(f"file://{os.path.abspath(full_path)}")
            orch.speak("Opening it now.", record_chat=False)
        except Exception as e:
            logging.debug("[core/handlers/code_gen.py:open] %s", e)
            orch.speak("I couldn't open the browser, but the file is saved.", record_chat=False)

    return True


def _parse_code_query(c):
    """Extract code query, save location, and language from command."""
    cmd = c.lower().strip()
    # Strip surrounding quotes/punctuation:  ""can you create..."".  -> "can you create..."
    cmd = cmd.strip(" \t\n\r\"'`.,;")
    query = None
    save_path = None
    language = "python"  # Default language

    # Detect language FIRST (before any parsing)
    lang_patterns = {
        "python": r"\b(python|py)\b",
        "javascript": r"\b(javascript|js|node)\b",
        "java": r"\b(java)\b",
        "cpp": r"\b(c\+\+|cpp|c plus plus)\b",
        "html": r"\b(html|web)\b",
        "css": r"\b(css|style|stylesheet)\b",
        "sql": r"\b(sql|database|query)\b",
        "ruby": r"\b(ruby|rails)\b",
        "go": r"\b(go|golang)\b",
        "rust": r"\b(rust|rustlang)\b",
        "swift": r"\b(swift|ios)\b",
        "kotlin": r"\b(kotlin|android)\b",
    }

    for lang, pattern in lang_patterns.items():
        if re.search(pattern, cmd, re.IGNORECASE):
            language = lang
            break

    # If nothing detected but it mentions page/web -> assume HTML
    if language == "python" and re.search(r"\b(page|website|web app|webapp|web page|landing)\b", cmd, re.IGNORECASE):
        language = "html"

    # Remove conversational framing: "can you create me a..." -> "create me a..."
    cleaned = cmd
    cleaned = re.sub(r"^(can|could|will|would|please|do you|would you|can you)\s+(you\s+)?(please\s+)?", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^i want\s+(?:you\s+)?(?:to\s+)?", "", cleaned, flags=re.IGNORECASE)

    # Simple approach: find "save to X" or "save in X" at the end
    save_match = re.search(r"save\s+(?:to|in|into)\s+(?:the\s+)?(\w+)\s*$", cleaned, re.IGNORECASE)
    if save_match:
        save_path = save_match.group(1)
        # Remove everything from "save" onwards
        query = cleaned[:save_match.start()].strip()
    else:
        # Check for "save to X" anywhere
        save_match = re.search(r"save\s+(?:to|in|into)\s+(?:the\s+)?(\w+)", cleaned, re.IGNORECASE)
        if save_match:
            save_path = save_match.group(1)
            # Remove the save part
            query = cleaned[:save_match.start()].strip()
        else:
            # Check for "save the code" or "save it" pattern (with optional language keyword)
            save_match = re.search(r"save\s+(?:the\s+)?(?:\w+\s+)?(?:code|script|program|file|result|output|it)\s*$", cleaned, re.IGNORECASE)
            if save_match:
                # No specific path mentioned, will use default
                query = cleaned[:save_match.start()].strip()
            else:
                query = cleaned

    # Remove code generation prefixes
    query = re.sub(r"^(tell|give|show|write|generate|create|get|find|make|build|design|develop|code)\s+(?:me\s+)?(?:a\s+)?(?:an\s+)?(?:the\s+)?", "", query, flags=re.IGNORECASE)

    query = re.sub(r"\b(web page|website|a web|an web|web)\b", "page", query, flags=re.IGNORECASE)

    # Clean up the query - remove language keywords and code-related words
    query = re.sub(r"\b(code|script|program|implementation|algorithm|function|class|from online|from the web)\b", "", query, flags=re.IGNORECASE)
    # Remove language keywords from query
    for lang_word in ["python", "java", "javascript", "js", "c++", "cpp", "html", "css", "sql", "ruby", "go", "rust", "swift", "kotlin"]:
        query = re.sub(r"\b" + re.escape(lang_word) + r"\b", "", query, flags=re.IGNORECASE)
# Remove trailing connecting words (including "using", "and", "with") — iterate until stable
    _connectors = r"using|and|or|the|a|an|my|me|myself|please|from|with|for|to|of|in|on|at"
    for _ in range(4):
        query = re.sub(r"\s+(" + _connectors + r")\s*$", "", query, flags=re.IGNORECASE)
        query = re.sub(r"^(?:the\s+)?(?:" + _connectors + r")\s+", "", query, flags=re.IGNORECASE)
        query = re.sub(r"\s+(" + _connectors + r")\s+", " ", query, flags=re.IGNORECASE)
        query = re.sub(r"[^a-zA-Z0-9 _-]", " ", query)
        query = re.sub(r"\s+", " ", query).strip()
        _stripped = query.strip()
        _words = _stripped.split()
        _done = len(_words) < 2 or not any(re.fullmatch(r"(?:" + _connectors + r")", w, flags=re.IGNORECASE) for w in _words)
        if _done:
            break
    # If still empty, fall back to generic subject so we never ask "what code?"
    if not query:
        query = cmd

    # If no save path detected, check if the user mentioned downloads/desktop/documents anywhere
    if not save_path:
        if re.search(r"\b(downloads?|desktop|documents?)\b", cmd, re.IGNORECASE):
            match = re.search(r"\b(downloads?|desktop|documents?)\b", cmd, re.IGNORECASE)
            save_path = match.group(1)
        elif re.search(r"\b(generate|create|make|build|design|write)\b", cmd, re.IGNORECASE):
            # User asked to create/make something -> default to Downloads
            save_path = Config.CODE_OUTPUT_DIR

    return query, save_path, language


def _clean_code(code):
    """Remove markdown code blocks and clean up the code."""
    # Remove markdown code blocks
    code = re.sub(r"```(?:\w+)?\n(.*?)\n```", r"\1", code, flags=re.DOTALL)
    code = re.sub(r"```", "", code)

    # Remove leading/trailing whitespace
    code = code.strip()

    return code


def _extension_for_language(language):
    extensions = {
        "python": ".py",
        "javascript": ".js",
        "java": ".java",
        "cpp": ".cpp",
        "html": ".html",
        "css": ".css",
        "sql": ".sql",
        "ruby": ".rb",
        "go": ".go",
        "rust": ".rs",
        "swift": ".swift",
        "kotlin": ".kt",
    }
    return extensions.get(language, ".py")


def _generate_filename(query, language):
    """Generate a filename from the code query."""
    # Clean the query to make a valid filename
    clean = re.sub(r'[^\w\s-]', '', query.lower())
    clean = re.sub(r'[-\s]+', '_', clean).strip('_')[:30]
    if not clean or clean in ('', '_'):
        clean = 'generated_code'

    return f"{clean}{_extension_for_language(language)}"
