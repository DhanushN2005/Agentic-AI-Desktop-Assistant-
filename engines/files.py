import difflib
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import webbrowser

from utils.config import Config
from utils.helpers import find_executable
from utils.name_index import get_shared_index

_LEADING_WORDS = {"delete", "remove", "erase", "trash", "the", "file", "folder", "please", "rename"}


def clean_target(query: str) -> str:
    """Strip only LEADING verb/article/'file'/'folder' tokens; preserve case and the rest."""
    toks = query.strip().split()
    while toks and toks[0].lower() in _LEADING_WORDS:
        toks.pop(0)
    return " ".join(toks).strip().strip("'\"")


class RecycleBinError(RuntimeError):
    """The Recycle Bin call failed; nothing was deleted."""


class FileManager:
    def __init__(self):
        self._cache: dict[str, str] = {}
        self._cache_lock = threading.Lock()
        self.last_candidates: list[str] = []
        self.last_opened_path = None
        self.last_created_path = None
        self._index_obj = get_shared_index()
        self._index_obj.refresh_async()

    # ---- thread-safe, validated cache (EN-2)
    def _cache_get(self, key: str):
        with self._cache_lock:
            path = self._cache.get(key)
        if path is None:
            return None
        if os.path.exists(path) or path.startswith("http"):
            return path
        with self._cache_lock:
            self._cache.pop(key, None)
        return None

    def _cache_set(self, key: str, path: str) -> None:
        with self._cache_lock:
            self._cache[key] = path

    @property
    def _all_names(self) -> list[str]:
        return list(set(Config.FOLDER_SHORTCUTS) | set(Config.APPS) | self._index_obj.names())

    def _suggest(self, q, n=3):
        return difflib.get_close_matches(q.lower(), self._all_names, n=n, cutoff=0.4)

    def _launch_path(self, path: str, is_run: bool = False):
        """Helper to run or open a file/application path safely."""
        if not path or not os.path.exists(path):
            raise FileNotFoundError(f"Path does not exist: {path}")
        if is_run and path.lower().endswith((".exe", ".bat", ".cmd", ".ps1")):
            subprocess.Popen([path], shell=False)
        elif is_run and path.lower().endswith(".py"):
            subprocess.Popen(["python", path], shell=False)
        else:
            os.startfile(path)

    def open_path(self, path: str) -> str:
        """Open exactly this (already chosen) path."""
        try:
            self._launch_path(path)
            self.last_opened_path = path
            return f"Opened {os.path.basename(path)}."
        except Exception as e:
            return f"I couldn't open it: {e}"

    def open_item(self, query: str, target_path: str = None) -> str:
        is_run = "run" in query.lower()
        q = re.sub(r"\b(open|run|launch|start|the|folder|app|application)\b", "", query).strip().lower()
        if not q:
            return "I heard you say open, but I didn't catch what you want me to open. Could you repeat that?"

        self.last_candidates = []
        cached = self._cache_get(q)
        if cached:
            try:
                if target_path:
                    subprocess.Popen([cached, target_path])
                else:
                    os.startfile(cached)
                return f"Opening {q}."
            except Exception as _e:
                logging.debug("cached open failed: %s", _e)
                with self._cache_lock:
                    self._cache.pop(q, None)

        # Check if q corresponds to a directory or project on desktop or search roots
        clean_q = re.sub(r"\b(created|my|the|new|project)\b", "", q).strip()
        desktop = Config.FOLDER_SHORTCUTS.get("desktop", "")
        if desktop and os.path.isdir(desktop):
            for entry in os.listdir(desktop):
                entry_path = os.path.join(desktop, entry)
                if os.path.isdir(entry_path):
                    entry_clean = entry.lower().replace("_", "").replace(" ", "").replace("-", "")
                    q_clean = clean_q.replace("_", "").replace(" ", "").replace("-", "")
                    if q_clean and (q_clean in entry_clean or entry_clean in q_clean):
                        try:
                            if target_path:
                                self._launch_path(entry_path, is_run)
                            else:
                                os.startfile(entry_path)
                            self._cache_set(q, entry_path)
                            self.last_opened_path = entry_path
                            return f"Opening project folder {entry}."
                        except Exception as _e:
                            logging.debug("Could not open desktop folder %s: %s", entry, _e)

        # App lookup (exact match first, then whole-word match)
        for app, path in Config.APPS.items():
            if re.search(r"\b" + re.escape(app) + r"\b", q):
                try:
                    if path.startswith("http"):
                        webbrowser.open(path)
                    else:
                        # Try to resolve path dynamically if it's an app
                        resolved_path = find_executable(app, path)
                        if os.path.exists(resolved_path):
                            if target_path:
                                subprocess.Popen([resolved_path, target_path])
                            else:
                                os.startfile(resolved_path)
                            self._cache_set(q, resolved_path)
                        else:
                            # Use os.startfile instead of shell for safety
                            try:
                                if target_path and os.path.exists(target_path):
                                    os.startfile(target_path)
                                else:
                                    os.startfile(path)
                            except Exception as _e:
                                logging.debug("[engines/files.py:73] Swallowed exception: %s: %s", type(_e).__name__, _e)
                                # Fail closed: 'start' is a cmd.exe builtin and
                                # would need a shell to run — do not shell out.
                                return f"Error opening {app}: {type(_e).__name__}"
                            self._cache_set(q, path)
                    return f"Opening {app}."
                except Exception as e:
                    logging.debug("[engines/files.py:79] Swallowed exception: %s: %s", type(e).__name__, e)
                    return f"Error opening {app}: {e}"

        file_tokens = [token for token in q.split() if "." in token and not token.endswith(".")]
        file_name = max(file_tokens, key=len) if file_tokens else None
        if file_name:
            for folder_name, folder_path in Config.FOLDER_SHORTCUTS.items():
                if folder_name in q and os.path.isdir(folder_path):
                    candidate = os.path.join(folder_path, file_name)
                    if os.path.isfile(candidate):
                        try:
                            self._launch_path(candidate, is_run)
                            self._cache_set(q, candidate)
                            self.last_opened_path = candidate
                            return f"{'Ran' if is_run else 'Found and opened'} {os.path.basename(candidate)}."
                        except Exception as e:
                            logging.debug("[engines/files.py:87] Swallowed exception: %s: %s", type(e).__name__, e)
                            return f"I found it, but couldn't open it: {e}"

            path = self._find_item_path(q)
            if not path and not self.last_candidates:
                path = self._find_item_path(file_name)
            if path:
                try:
                    self._launch_path(path, is_run)
                    self._cache_set(q, path)
                    self.last_opened_path = path
                    return f"{'Ran' if is_run else 'Found and opened'} {os.path.basename(path)}."
                except Exception as e:
                    logging.debug("[engines/files.py:104] Swallowed exception: %s: %s", type(e).__name__, e)
                    return f"I found it, but couldn't open it: {e}"
            if self.last_candidates:
                return self._ambiguous_reply(self.last_candidates)
            return f"I couldn't find '{file_name}' on your system."

        # Folder lookup
        for name, path in Config.FOLDER_SHORTCUTS.items():
            if name in q and os.path.exists(path):
                os.startfile(path)
                self._cache_set(q, path)
                return f"Opening {name}."

        # Stop-words and length guards for fuzzy/deep lookups
        words = q.split()
        stop_words = {"my", "the", "a", "an", "on", "off", "of", "to", "in", "at", "for", "with", "app", "folder", "file", "device"}
        filtered_words = [w for w in words if w not in stop_words]

        # If all words are stop words, or the query itself is a stop word, completely block fuzzy/deep search
        if not filtered_words or q in stop_words:
            return f"I couldn't find '{q}' on your system."

        keyword = filtered_words[-1]

        # Enforce length >= 4 and strict stop-word filters to block incorrect activations (such as opening CrossDevice for "of")
        if len(keyword) < 4 or keyword in stop_words:
            return f"I couldn't find '{q}' on your system. Please be more specific."

        # Folder/File deep lookup (new robust method)
        path = self._find_item_path(q)
        if not path and not self.last_candidates:
            path = self._find_item_path(keyword)

        if path:
            try:
                self._launch_path(path, is_run)
                self._cache_set(q, path)
                self.last_opened_path = path
                verb = "Ran" if is_run else "Found and opened"
                return f"{verb} {os.path.basename(path)}."
            except Exception as e:
                logging.debug("[engines/files.py:115] Swallowed exception: %s: %s", type(e).__name__, e)
                self.last_opened_path = None
                return f"I found it, but couldn't open it: {e}"

        if self.last_candidates:
            return self._ambiguous_reply(self.last_candidates)

        # Fuzzy suggestion (only for safe keywords)
        sugg = self._suggest(keyword)
        if sugg:
            return f"NOT_FOUND:{q}|{','.join(sugg)}"
        return f"I couldn't find '{q}' anywhere on your system."

    def create_folder(self, cmd: str) -> str:
        loc = Config.FOLDER_SHORTCUTS.get("desktop", Config.USER_HOME)
        cmd_lower = cmd.lower()
        for n, p in Config.FOLDER_SHORTCUTS.items():
            if f"in {n}" in cmd_lower or f"on {n}" in cmd_lower or f"at {n}" in cmd_lower or f"inside {n}" in cmd_lower or n in cmd_lower:
                loc = p
                break

        # Dynamic Drive Detection (e.g., 'e drive', 'drive e', or 'e:\')
        import re
        drive_match = re.search(r"\b(?:([a-zA-Z])\s+drive|drive\s+([a-zA-Z]))\b", cmd, re.IGNORECASE)
        if drive_match:
            drive_let = drive_match.group(1) or drive_match.group(2)
            loc = f"{drive_let.upper()}:\\"
        else:
            drive_match2 = re.search(r"\b([a-zA-Z]):\\", cmd, re.IGNORECASE)
            if drive_match2:
                loc = f"{drive_match2.group(1).upper()}:\\"

        # Absolute path provided directly
        absolute_match = re.search(r"([a-zA-Z]:\\[^\s]+)", cmd)
        if absolute_match:
            return self._create_absolute(absolute_match.group(1))
        name = "Flexie_Folder"
        if "named" in cmd:
            name = cmd.split("named")[-1].strip()
        elif "called" in cmd:
            name = cmd.split("called")[-1].strip()
        else:
            # Try to extract name from command if user says "create a folder in desktop notes" or "create folder test"
            rem = re.sub(r"\b(create|make|new|a|the|folder|directory|in|on|at|inside|desktop|downloads|documents)\b", "", cmd, flags=re.IGNORECASE).strip()
            if rem:
                name = rem.split()[0].strip()

        # Clean up name: stop at prepositions (e.g., "dhanush on desktop" -> "dhanush")
        for stop in [" on ", " at ", " in ", " inside "]:
            if stop in f" {name} ":
                name = name.split(stop.strip())[0].strip()
        name = re.sub(r'[\\/*?:"<>|]', "", name).strip() or "Flexie_Folder"
        path = os.path.join(loc, name)

        # Priority 1 & 6: Execute with focus and verification loop
        retries = 2
        for attempt in range(retries):
            try:
                os.makedirs(path, exist_ok=True)
                # Verification: verify folder exists on system
                if os.path.isdir(path):
                    return path
            except Exception as e:
                logging.debug("[engines/files.py:167] Swallowed exception: %s: %s", type(e).__name__, e)
                if attempt == retries - 1:
                    raise e
                time.sleep(0.2)
        return path # Return path for context chaining

    def _create_absolute(self, path: str) -> str:
        import time

        from utils.path_jail import is_system_location
        if is_system_location(path):
            raise ValueError(f"Refusing to create system location: {path}")
        retries = 2
        for attempt in range(retries):
            try:
                os.makedirs(path, exist_ok=True)
                if os.path.isdir(path):
                    return path
            except Exception as e:
                logging.debug("[engines/files.py:181] Swallowed exception: %s: %s", type(e).__name__, e)
                if attempt == retries - 1:
                    raise e
                time.sleep(0.2)
        return path

    def create_document(self, cmd: str, content: str = "", target_dir: str = None) -> str:
        """Creates a document with intelligent naming, extension detection, and strict verification."""
        loc = target_dir or Config.FOLDER_SHORTCUTS.get("desktop", Config.USER_HOME)

        # 3. Handle Location
        cmd_l_loc = cmd.lower()
        for n, p in Config.FOLDER_SHORTCUTS.items():
            if f"in {n}" in cmd_l_loc or f"on {n}" in cmd_l_loc or f"at {n}" in cmd_l_loc or f"inside {n}" in cmd_l_loc or n in cmd_l_loc:
                loc = p
                break

        # Dynamic Drive Detection
        import re
        drive_match = re.search(r"\b(?:([a-zA-Z])\s+drive|drive\s+([a-zA-Z]))\b", cmd, re.IGNORECASE)
        if drive_match:
            drive_let = drive_match.group(1) or drive_match.group(2)
            loc = f"{drive_let.upper()}:\\"
        else:
            drive_match2 = re.search(r"\b([a-zA-Z]):\\", cmd, re.IGNORECASE)
            if drive_match2:
                loc = f"{drive_match2.group(1).upper()}:\\"

        # Absolute path provided directly
        absolute_match = re.search(r"([a-zA-Z]:\\[^\s\\]+)", cmd)
        if absolute_match:
            loc = absolute_match.group(1)
            os.makedirs(loc, exist_ok=True)

        # 1. Determine Extension (aware of all common file types)
        ext = ".txt"  # default
        cmd_l = cmd.lower()
        if any(x in cmd_l for x in ["html", "web page", "webpage", "landing page", "login page", "website", "homepage", "home page"]):
            ext = ".html"
        elif any(x in cmd_l for x in ["css", "style sheet", "stylesheet"]):
            ext = ".css"
        elif "python" in cmd_l or "py file" in cmd_l or "py script" in cmd_l:
            ext = ".py"
        elif any(x in cmd_l for x in ["javascript", "js file"]):
            ext = ".js"
        elif "json" in cmd_l or "json file" in cmd_l:
            ext = ".json"
        elif any(x in cmd_l for x in ["markdown", "md file", " md ", " readme"]):
            ext = ".md"

        # 2. Extract Name
        name = "new_file"
        if "named" in cmd.lower():
            name = cmd.lower().split("named")[-1].split("with")[0].strip()
        elif "called" in cmd.lower():
            name = cmd.lower().split("called")[-1].split("with")[0].strip()
        elif "for" in cmd.lower() and ext == ".py":
            # Extract purpose (e.g., "py file for odd or even" -> "odd_or_even")
            name = cmd.lower().split("for")[-1].strip()
        elif "about" in cmd.lower():
            name = cmd.lower().split("about")[-1].strip()

        # Clean name
        import datetime
        import time
        timestamp = datetime.datetime.now().strftime("%H%M")
        name = re.sub(r"[^\w\s-]", "", name).replace(" ", "_")
        name = f"{name}_flexie({timestamp})"

        if not name.endswith(ext):
            name += ext

        path = self._unique_path(os.path.join(loc, name))
        name = os.path.basename(path)

        # Priority 1: Execution verification and self-healing loop
        success = False
        err_msg = ""
        for _ in range(2):
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)

                # Verification Check: file exists on disk and is non-empty (if content was provided)
                if os.path.exists(path):
                    if len(content) == 0 or os.path.getsize(path) > 0:
                        success = True
                        break
            except Exception as write_err:
                logging.debug("[engines/files.py:258] Swallowed exception: %s: %s", type(write_err).__name__, write_err)
                err_msg = str(write_err)
                time.sleep(0.3)

        if success:
            # Update cache/context
            self._cache_set(name.lower(), path)
            self.last_created_path = path

            # Automatically open the newly created document!
            try:
                os.startfile(path)
            except Exception as open_err:
                logging.debug("[engines/files.py:270] Swallowed exception: %s: %s", type(open_err).__name__, open_err)
                pass

            return f"Created document '{name}' at {os.path.basename(loc)}."
        else:
            # Priority 6: Recovery self-healing clipboard fallback
            self.last_created_path = None
            try:
                import pyperclip
                pyperclip.copy(content)
                return f"Verification Alert: Failed to write file due to permissions or disk error. However, self-healing has saved the content to your clipboard. You can press Ctrl+V to paste it manually. Details: {err_msg}"
            except Exception as _e:
                logging.debug("[engines/files.py:281] Swallowed exception: %s: %s", type(_e).__name__, _e)
                return f"Failed to create document: {err_msg}"

    def find_files(self, name: str) -> list[str]:
        """Return up to 5 files whose name contains ``name`` (uses the shared bounded index)."""
        return [p for p in self._index_obj.partial(name, limit=25) if os.path.isfile(p)][:5]



    # ------------------------------------------------------------------ organize (EN-21)
    def _undo_log_path(self) -> str:
        from utils.paths import data_file
        return data_file("organize_undo.json")

    def organize_desktop(self) -> str:
        desk = Config.FOLDER_SHORTCUTS["desktop"]
        cats = {
            "Images": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg"},
            "Documents": {".pdf", ".docx", ".doc", ".txt", ".pptx", ".xlsx"},
            "Videos": {".mp4", ".mkv", ".avi", ".mov"},
            "Music": {".mp3", ".wav", ".flac"},
            "Code": {".py", ".js", ".ts", ".html", ".css", ".java", ".cpp"},
            "Archives": {".zip", ".rar", ".7z", ".tar", ".gz"},
            "Others": set()
        }
        moved = 0
        moves: list[dict] = []
        for item in os.listdir(desk):
            src = os.path.join(desk, item)
            if os.path.isdir(src) or item.lower() == "desktop.ini" or item.lower().endswith(".lnk"):
                continue
            ext = os.path.splitext(item)[1].lower()
            for cat, exts in cats.items():
                if ext in exts or cat == "Others":
                    dst_dir = os.path.join(desk, cat)
                    os.makedirs(dst_dir, exist_ok=True)
                    dst = os.path.join(dst_dir, item)
                    if not os.path.exists(dst):
                        shutil.move(src, dst)
                        moves.append({"src": src, "dst": dst})
                        moved += 1
                    break
        if moves:
            try:
                import json
                with open(self._undo_log_path(), "w", encoding="utf-8") as f:
                    json.dump({"time": time.time(), "moves": moves}, f)
            except Exception as e:
                logging.debug("organize undo log failed: %s", e)
        return f"Organized {moved} files on your Desktop." + (" Say undo organize to put them back." if moved else "")

    def undo_organize(self) -> str:
        import json
        try:
            with open(self._undo_log_path(), encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return "I have no desktop organizing to undo."
        restored = 0
        for mv in reversed(data.get("moves", [])):
            src, dst = mv["src"], mv["dst"]
            try:
                if os.path.exists(dst) and not os.path.exists(src):
                    shutil.move(dst, src)
                    restored += 1
                    parent = os.path.dirname(dst)
                    if not os.listdir(parent):
                        os.rmdir(parent)
            except Exception as e:
                logging.debug("undo move failed: %s", e)
        try:
            os.remove(self._undo_log_path())
        except OSError:
            pass
        return f"Restored {restored} files to your Desktop."

    # ------------------------------------------------------------------ resolver (EN-1/2)
    def _user_dirs(self) -> list[str]:
        dirs = [Config.FOLDER_SHORTCUTS.get("desktop"), Config.FOLDER_SHORTCUTS.get("documents"),
                Config.FOLDER_SHORTCUTS.get("downloads") or os.path.join(Config.USER_HOME, "Downloads")]
        return [d for d in dirs if d and os.path.isdir(d)]

    @staticmethod
    def _dedupe(paths: list[str]) -> list[str]:
        seen, uniq = set(), []
        for p in paths:
            n = os.path.normcase(os.path.abspath(p))
            if n not in seen:
                seen.add(n)
                uniq.append(p)
        return uniq

    def _exact_matches(self, key: str) -> list[str]:
        out: list[str] = []
        for d in self._user_dirs():
            try:
                for item in os.listdir(d):
                    if item.lower() == key:
                        out.append(os.path.join(d, item))
            except OSError:
                continue
        out.extend(self._index_obj.exact(key))
        return self._dedupe(out)

    def _partial_matches(self, key: str, limit: int = 6) -> list[str]:
        out: list[str] = []
        for d in self._user_dirs():
            try:
                for item in os.listdir(d):
                    if key in item.lower():
                        out.append(os.path.join(d, item))
            except OSError:
                continue
        if len(key) > 3:
            out.extend(self._index_obj.partial(key, limit=limit))
        return self._dedupe(out)[:limit]

    def resolve_item(self, query: str, exact_only: bool = False):
        """Resolve a spoken name ONCE. Returns (path, candidates).

        path is set only for one unambiguous target; otherwise candidates lists
        the choices the user must pick from (empty list = nothing found).
        """
        name = clean_target(query)
        if not name:
            return None, []
        if os.path.isabs(name) and os.path.exists(name):
            return name, []
        key = name.lower()
        cached = self._cache_get(key)
        if cached and (not exact_only or os.path.basename(cached).lower() == key):
            return cached, []
        for s_name, s_path in Config.FOLDER_SHORTCUTS.items():
            if key == s_name and os.path.exists(s_path):
                return s_path, []
        exact = self._exact_matches(key)
        if len(exact) == 1:
            self._cache_set(key, exact[0])
            return exact[0], []
        if len(exact) > 1:
            return None, exact[:6]
        partial = self._partial_matches(key)
        if exact_only:
            return None, partial
        if len(partial) == 1:
            self._cache_set(key, partial[0])
            return partial[0], []
        return None, partial

    def _find_item_path(self, name: str):
        path, cands = self.resolve_item(name)
        self.last_candidates = [] if path else cands
        return path

    def _ambiguous_reply(self, cands: list[str]) -> str:
        lines = [f"{i + 1}. {os.path.basename(p)} in {os.path.basename(os.path.dirname(p)) or os.path.dirname(p)}"
                 for i, p in enumerate(cands)]
        return "I found several matches: " + "; ".join(lines) + ". Please tell me which number you mean."

    # ------------------------------------------------------------------ rename (EN-11)
    def rename_item(self, cmd: str) -> str:
        """Renames a file or folder. Syntax: rename [old] to [new]"""
        parts = re.split(r"\s+(?:to|as)\s+", cmd.strip(), maxsplit=1, flags=re.IGNORECASE)
        if len(parts) < 2:
            return "Please say 'rename [old name] to [new name]'."

        old_name = clean_target(parts[0])
        new_name = parts[1].strip().strip("'\"").rstrip(".").strip()  # case preserved
        from utils.path_jail import is_basename_safe, is_system_location
        if not new_name or not is_basename_safe(new_name):
            return f"Rename failed: '{new_name}' is not a plain file/folder name."

        path, cands = self.resolve_item(old_name)
        if not path:
            self.last_candidates = cands
            if cands:
                return self._ambiguous_reply(cands)
            return f"I couldn't find '{old_name}' on your system."
        if is_system_location(path):
            return f"Rename failed: '{old_name}' is a protected system location."

        parent = os.path.dirname(os.path.abspath(path))
        if os.path.isfile(path):
            old_ext = os.path.splitext(path)[1]
            if "." not in new_name and old_ext:
                new_name += old_ext

        new_path = os.path.join(parent, new_name)
        if os.path.exists(new_path) and os.path.normcase(new_path) != os.path.normcase(os.path.abspath(path)):
            return f"Rename failed: '{new_name}' already exists."
        try:
            os.rename(path, new_path)
            with self._cache_lock:
                self._cache.clear()
            return f"Successfully renamed '{os.path.basename(path)}' to '{new_name}'."
        except Exception as e:
            logging.debug("rename failed: %s: %s", type(e).__name__, e)
            return f"Rename failed: {e}"

    # ------------------------------------------------------------------ delete (EN-1/2/22)
    def delete_path(self, path: str) -> str:
        """Delete exactly ``path`` (Recycle Bin only; refuses if that fails)."""
        from utils.path_jail import is_system_location
        if not path or not os.path.exists(path):
            return "That item no longer exists."
        if is_system_location(path):
            return f"Delete failed: '{os.path.basename(path)}' is a protected system location."
        try:
            self._recycle_or_remove(path)
            with self._cache_lock:
                self._cache.clear()
            return f"Moved '{os.path.basename(path)}' to the Recycle Bin."
        except RecycleBinError as e:
            return f"I could not move it to the Recycle Bin, so I did NOT delete it ({e})."
        except Exception as e:
            logging.debug("delete failed: %s: %s", type(e).__name__, e)
            return f"Delete failed: {e}"

    def delete_item(self, query: str) -> str:
        """Deletes ONE exactly-named file or folder; never guesses among partial matches."""
        path, cands = self.resolve_item(query, exact_only=True)
        if not path:
            self.last_candidates = cands
            if cands:
                return self._ambiguous_reply(cands) + " Nothing was deleted."
            return f"I couldn't find '{clean_target(query)}' to delete."
        return self.delete_path(path)

    def _recycle_or_remove(self, path: str):
        """Send item to the Windows Recycle Bin; raise RecycleBinError (never delete permanently) on failure."""
        if os.name != "nt":
            raise RecycleBinError("no Recycle Bin on this platform")
        try:
            import ctypes
            from ctypes import wintypes

            class _SHFILEOPSTRUCTW(ctypes.Structure):
                _fields_ = [
                    ("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT),
                    ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR),
                    ("fFlags", wintypes.WORD), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR),
                ]
            fileop = _SHFILEOPSTRUCTW(
                None, 3, os.path.abspath(path) + "\0\0", None,
                0x0040 | 0x0010 | 0x0004, False, None, None
            )
            rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(fileop))
        except Exception as e:
            raise RecycleBinError(f"{type(e).__name__}") from e
        if rc != 0 or os.path.exists(path):
            raise RecycleBinError(f"shell error {rc}")

    # ------------------------------------------------------------------ save (EN-23)
    @staticmethod
    def _unique_path(path: str) -> str:
        if not os.path.exists(path):
            return path
        base, ext = os.path.splitext(path)
        n = 2
        while os.path.exists(f"{base} ({n}){ext}"):
            n += 1
        return f"{base} ({n}){ext}"

    def save_file(self, content: str, filename: str) -> str:
        """Saves content in Documents; never overwrites an existing file (uses a unique name)."""
        from utils.path_jail import is_basename_safe
        clean_name = os.path.basename(filename.strip().replace("\\", "/"))
        if not is_basename_safe(clean_name):
            return "Save failed: Invalid or unsafe filename."
        loc = Config.FOLDER_SHORTCUTS.get("documents", Config.USER_HOME)
        if not clean_name.endswith((".txt", ".md", ".py", ".js")):
            clean_name += ".txt"

        path = self._unique_path(os.path.join(loc, clean_name))
        saved_name = os.path.basename(path)

        success = False
        err_msg = ""
        for _ in range(3):
            try:
                with open(path, "x", encoding="utf-8") as f:
                    f.write(content)
                if os.path.exists(path) and (len(content) == 0 or os.path.getsize(path) > 0):
                    success = True
                    break
            except FileExistsError:
                path = self._unique_path(path)
                saved_name = os.path.basename(path)
            except Exception as e:
                logging.debug("save failed: %s: %s", type(e).__name__, e)
                err_msg = str(e)
                time.sleep(0.2)

        if success:
            return f"File '{saved_name}' saved successfully in your Documents."
        try:
            import pyperclip
            pyperclip.copy(content)
            return f"Verification Alert: Failed to save file '{filename}'. Stored content on clipboard as fallback. Details: {err_msg}"
        except Exception as _e:
            logging.debug("clipboard fallback failed: %s", _e)
            return f"Failed to save file: {err_msg}"
