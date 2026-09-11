import os
import threading
import difflib
import re
import webbrowser
import shutil
import subprocess
from typing import Dict, List
from utils.config import Config
from utils.helpers import get_numbers, is_online, find_executable

class FileManager:
    def __init__(self):
        self._cache: Dict[str, str] = {}
        self._all_names: List[str] = []
        threading.Thread(target=self._index, daemon=True).start()

    def _index(self):
        names = list(Config.FOLDER_SHORTCUTS) + list(Config.APPS)
        for root in Config.SEARCH_ROOTS:
            if not os.path.exists(root): continue
            for r, dirs, _ in os.walk(root):
                bad = ["Windows", "Program Files", "AppData", "node_modules", ".git", "$"]
                if any(b in r for b in bad):
                    dirs.clear()
                    continue
                names += [d.lower() for d in dirs]
                if r.count(os.sep) - root.count(os.sep) > 4:
                    dirs.clear()
        self._all_names = list(set(names))

    def _suggest(self, q, n=3):
        return difflib.get_close_matches(q.lower(), self._all_names, n=n, cutoff=0.4)

    def open_item(self, query: str, target_path: str = None) -> str:
        q = re.sub(r"\b(open|run|launch|start|the|folder|app|application)\b", "", query).strip().lower()
        if not q:
            return "I heard you say open, but I didn't catch what you want me to open. Could you repeat that?"

        if q in self._cache:
            try:
                path = self._cache[q]
                if target_path:
                    subprocess.Popen([path, target_path])
                else:
                    os.startfile(path)
                return f"Opening {q}."
            except:
                del self._cache[q]

        # App lookup
        for app, path in Config.APPS.items():
            if app in q:
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
                            self._cache[q] = resolved_path
                        else:
                            # Use os.startfile instead of shell for safety
                            try:
                                if target_path and os.path.exists(target_path):
                                    os.startfile(target_path)
                                else:
                                    os.startfile(path)
                            except:
                                cmd = f'start {app}'
                                if target_path: cmd += f' "{target_path}"'
                                subprocess.Popen(cmd, shell=True)
                            self._cache[q] = path
                    return f"Opening {app}."
                except Exception as e:
                    return f"Error opening {app}: {e}"

        # Folder lookup
        for name, path in Config.FOLDER_SHORTCUTS.items():
            if name in q and os.path.exists(path):
                os.startfile(path)
                self._cache[q] = path
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
        if not path:
            path = self._find_item_path(keyword)
            
        if path:
            try:
                os.startfile(path)
                self._cache[q] = path
                self.last_opened_path = path
                return f"Found and opened {os.path.basename(path)}."
            except Exception as e:
                self.last_opened_path = None
                return f"I found it, but couldn't open it: {e}"

        # Fuzzy suggestion (only for safe keywords)
        sugg = self._suggest(keyword)
        if sugg:
            return f"NOT_FOUND:{q}|{','.join(sugg)}"
        return f"I couldn't find '{q}' anywhere on your system."

    def create_folder(self, cmd: str) -> str:
        loc = Config.FOLDER_SHORTCUTS.get("desktop", Config.USER_HOME)
        for n, p in Config.FOLDER_SHORTCUTS.items():
            if f"in {n}" in cmd:
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
            
        # Clean up name: stop at prepositions (e.g., "dhanush on desktop" -> "dhanush")
        for stop in [" on ", " at ", " in "]:
            if stop in f" {name} ":
                name = name.split(stop.strip())[0].strip()
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
                if attempt == retries - 1:
                    raise e
                time.sleep(0.2)
        return path # Return path for context chaining

    def _create_absolute(self, path: str) -> str:
        import time
        retries = 2
        for attempt in range(retries):
            try:
                os.makedirs(path, exist_ok=True)
                if os.path.isdir(path):
                    return path
            except Exception as e:
                if attempt == retries - 1:
                    raise e
                time.sleep(0.2)
        return path

    def create_document(self, cmd: str, content: str = "", target_dir: str = None) -> str:
        """Creates a document with intelligent naming, extension detection, and strict verification."""
        loc = target_dir or Config.FOLDER_SHORTCUTS.get("desktop", Config.USER_HOME)
        
        # 3. Handle Location
        for n, p in Config.FOLDER_SHORTCUTS.items():
            if f"in {n}" in cmd.lower() or f"on {n}" in cmd.lower():
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
            
        # 1. Determine Extension
        ext = ".txt"
        if any(x in cmd.lower() for x in ["python", "py file", "script", "code", "program"]):
            ext = ".py"
        elif "markdown" in cmd.lower() or " md " in cmd.lower():
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
            
        path = os.path.join(loc, name)
        
        # Priority 1: Execution verification and self-healing loop
        success = False
        err_msg = ""
        for attempt in range(2):
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
                
                # Verification Check: file exists on disk and is non-empty (if content was provided)
                if os.path.exists(path):
                    if len(content) == 0 or os.path.getsize(path) > 0:
                        success = True
                        break
            except Exception as write_err:
                err_msg = str(write_err)
                time.sleep(0.3)
        
        if success:
            # Update cache/context
            self._cache[name.lower()] = path
            self.last_created_path = path
            
            # Automatically open the newly created document!
            try:
                os.startfile(path)
            except Exception as open_err:
                pass
                
            return f"Created document '{name}' at {os.path.basename(loc)}."
        else:
            # Priority 6: Recovery self-healing clipboard fallback
            self.last_created_path = None
            try:
                import pyperclip
                pyperclip.copy(content)
                return f"Verification Alert: Failed to write file due to permissions or disk error. However, self-healing has saved the content to your clipboard. You can press Ctrl+V to paste it manually. Details: {err_msg}"
            except:
                return f"Failed to create document: {err_msg}"

    def find_files(self, name: str) -> List[str]:
        name = name.lower()
        results = []
        for root in Config.SEARCH_ROOTS:
            if not os.path.exists(root): continue
            for r, dirs, files in os.walk(root):
                bad = ["Windows", "Program Files", "AppData", ".git", "$"]
                if any(b in r for b in bad):
                    dirs.clear()
                    continue
                for f in files:
                    if name in f.lower():
                        results.append(os.path.join(r, f))
                if len(results) >= 5:
                    return results
        return results

    def organize_desktop(self) -> str:
        desk = Config.FOLDER_SHORTCUTS["desktop"]
        cats = {
            "Images": {".jpg",".jpeg",".png",".gif",".bmp",".svg"},
            "Documents": {".pdf",".docx",".doc",".txt",".pptx",".xlsx"},
            "Videos": {".mp4",".mkv",".avi",".mov"},
            "Music": {".mp3",".wav",".flac"},
            "Code": {".py",".js",".ts",".html",".css",".java",".cpp"},
            "Archives": {".zip",".rar",".7z",".tar",".gz"},
            "Others": set()
        }
        moved = 0
        for item in os.listdir(desk):
            src = os.path.join(desk, item)
            if os.path.isdir(src): continue
            ext = os.path.splitext(item)[1].lower()
            for cat, exts in cats.items():
                if ext in exts or cat == "Others":
                    dst_dir = os.path.join(desk, cat)
                    os.makedirs(dst_dir, exist_ok=True)
                    dst = os.path.join(dst_dir, item)
                    if not os.path.exists(dst):
                        shutil.move(src, dst)
                        moved += 1
                    break
        return f"Organized {moved} files on your Desktop."

    def rename_item(self, cmd: str) -> str:
        """Renames a file or folder. Syntax: rename [old] to [new]"""
        parts = re.split(r"\s+to\s+|\s+as\s+", cmd.lower())
        if len(parts) < 2: return "Please say 'rename [old name] to [new name]'."
        
        old_name = re.sub(r"^(rename|folder|file|the)\s+", "", parts[0]).strip()
        new_name = parts[1].strip()
        
        path = self._find_item_path(old_name)
        if not path: return f"I couldn't find '{old_name}' on your system."
        
        parent = os.path.dirname(path)
        # If renaming a file, try to keep the extension if the user didn't provide one
        if os.path.isfile(path):
            old_ext = os.path.splitext(path)[1]
            if "." not in new_name and old_ext:
                new_name += old_ext
                
        new_path = os.path.join(parent, new_name)
        try:
            os.rename(path, new_path)
            return f"Successfully renamed '{old_name}' to '{new_name}'."
        except Exception as e:
            return f"Rename failed: {e}"

    def delete_item(self, query: str) -> str:
        """Deletes a file or folder. (Safe check should be in orchestrator)"""
        name = re.sub(r"^(delete|remove|erase|the)\s+", "", query.lower()).strip()
        path = self._find_item_path(name)
        if not path: return f"I couldn't find '{name}' to delete."
        
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            return f"Successfully deleted '{name}'."
        except Exception as e:
            return f"Delete failed: {e}"

    def save_file(self, content: str, filename: str) -> str:
        """Saves content to a file in the Documents folder by default with strict verification."""
        loc = Config.FOLDER_SHORTCUTS.get("documents", Config.USER_HOME)
        if not filename.endswith((".txt", ".md", ".py", ".js")):
            filename += ".txt"
        
        path = os.path.join(loc, filename)
        
        success = False
        err_msg = ""
        for attempt in range(2):
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
                # Verification Check
                if os.path.exists(path) and (len(content) == 0 or os.path.getsize(path) > 0):
                    success = True
                    break
            except Exception as e:
                err_msg = str(e)
                time.sleep(0.2)
                
        if success:
            return f"File '{filename}' saved successfully in your Documents."
        else:
            # Self-healing fallback
            try:
                import pyperclip
                pyperclip.copy(content)
                return f"Verification Alert: Failed to save file '{filename}'. Stored content on clipboard as fallback. Details: {err_msg}"
            except:
                return f"Failed to save file: {err_msg}"

    def _find_item_path(self, name: str) -> str:
        """Helper to find the full path of an item by name with performance tiers."""
        name = name.lower()
        if os.path.exists(name): return name
        if name in self._cache: return self._cache[name]
        
        # Tier 1: Shortcuts (Instant)
        for s_name, s_path in Config.FOLDER_SHORTCUTS.items():
            if name == s_name: return s_path

        # Tier 2: Common User Folders (Fast)
        search_dirs = [
            Config.FOLDER_SHORTCUTS.get("desktop"),
            Config.FOLDER_SHORTCUTS.get("documents"),
            os.path.join(Config.USER_HOME, "Downloads")
        ]
        # Exact match first
        for d in search_dirs:
            if d and os.path.exists(d):
                try:
                    for item in os.listdir(d):
                        if item.lower() == name:
                            p = os.path.join(d, item)
                            self._cache[name] = p
                            return p
                except: continue
                
        # Substring match second
        for d in search_dirs:
            if d and os.path.exists(d):
                try:
                    for item in os.listdir(d):
                        if name in item.lower():
                            p = os.path.join(d, item)
                            self._cache[name] = p
                            return p
                except: continue

        # Tier 3: Limited Deep Search (Moderate)
        # Exact match first
        for root in Config.SEARCH_ROOTS:
            if not os.path.exists(root): continue
            for r, dirs, files in os.walk(root):
                bad = ["Windows", "Program Files", "AppData", ".git", "$", "node_modules"]
                if any(b in r for b in bad):
                    dirs.clear(); continue
                depth = r.count(os.sep) - root.count(os.sep)
                if depth > 3:
                    dirs.clear(); continue
                for item in dirs + files:
                    if item.lower() == name:
                        p = os.path.join(r, item)
                        self._cache[name] = p
                        return p

        # Substring match second
        for root in Config.SEARCH_ROOTS:
            if not os.path.exists(root): continue
            for r, dirs, files in os.walk(root):
                bad = ["Windows", "Program Files", "AppData", ".git", "$", "node_modules"]
                if any(b in r for b in bad):
                    dirs.clear(); continue
                depth = r.count(os.sep) - root.count(os.sep)
                if depth > 3:
                    dirs.clear(); continue
                for item in dirs + files:
                    if len(name) > 3 and name in item.lower():
                        p = os.path.join(r, item)
                        self._cache[name] = p
                        return p
        return None
