import json
import os
import re
import time

from engines.system import SystemCtrl
import logging


class ContextMemory:
    """Advanced context memory for DOM, workflows, and multi-step tasks with dynamic session expiration."""
    def __init__(self, memory_engine=None):
        self.mem = memory_engine
        self.last_app = self._load("last_app")
        self.last_query = self._load("last_query")
        self.last_cmd = self._load("last_cmd")
        self.last_browser = self._load("last_browser", "chrome")
        self.last_screenshot = self._load("last_screenshot")
        self.last_url = self._load("last_url")
        self.last_selector = self._load("last_selector")
        self.active_engine = self._load("active_engine")
        self.last_yt_query = self._load("last_yt_query")
        self.last_path = self._load("last_path")

        # Stateful session workflow parameters
        self.last_response = self._load("last_response")
        self.active_document = self._load("active_document")
        self.last_search = self._load("last_search")

        # Browser situational context
        self.browser_open = False
        self.active_browser = self._load("active_browser", "")

        # New Context Tracker registers
        self.focused_app = None
        self.clipboard_state = None
        self.last_generated_content = self.last_response
        self.current_topic = self._load("current_topic")
        self.active_goal = self._load("active_goal")
        self.last_sdd = self._load("last_sdd")
        self.active_artifact = self._load_artifact()

        # Cross-app data registers
        self.registers = {}

        # Pending action state (for multi-turn conversations like "set timer" → "30 seconds")
        self.pending_action = None
        self.pending_action_data = {}

        # Session duration timer (5 minutes session window)
        self.session_duration = 300.0
        try:
            stored_time = self._load("session_time")
            self.session_time = float(stored_time) if stored_time else time.time()
        except Exception as _e:
            logging.debug("[core/context_memory.py:47] Swallowed exception: %s: %s", type(_e).__name__, _e)
            self.session_time = time.time()

        # Session dynamic cleanup on startup if expired
        if time.time() - self.session_time > self.session_duration:
            self.clear_session()

        # Sync system focus and clipboard immediately on init
        self.sync_system_state()

    def set_pending_action(self, action: str, data: dict = None):
        """Set a pending action that expects a follow-up response."""
        self.pending_action = action
        self.pending_action_data = data or {}

    def clear_pending_action(self):
        """Clear the pending action state."""
        self.pending_action = None
        self.pending_action_data = {}

    def sync_system_state(self):
        """Fetches the actual real-time operating system window focus and clipboard content."""
        try:
            self.focused_app = SystemCtrl.get_active_window_title()
            self.clipboard_state = SystemCtrl.get_clipboard()
        except Exception as _e:
            logging.debug("[core/context_memory.py:72] Swallowed exception: %s: %s", type(_e).__name__, _e)
            pass

    def clear_session(self):
        """Soft session clean up to discard temporary stale references."""
        self.last_response = None
        self.last_generated_content = None
        self.last_search = None
        self.active_document = None
        self.last_app = None
        self.last_path = None
        self.current_topic = None
        self.active_goal = None
        self.last_sdd = None
        self.active_artifact = None
        self.session_time = time.time()
        if self.mem:
            for k in ["last_response", "last_search", "active_document", "last_app", "last_path", "session_time", "current_topic", "active_goal", "last_sdd", "active_artifact"]:
                try:
                    self.mem.store(f"ctx_{k}", "")
                except Exception as _e:
                    logging.debug("[core/context_memory.py:90] Swallowed exception: %s: %s", type(_e).__name__, _e)
                    pass

    def _load(self, key, default=None):
        if not self.mem:
            return default
        return self.mem.recall(f"ctx_{key}") or default

    def _save(self, key, val):
        if self.mem and val is not None:
            self.mem.store(f"ctx_{key}", str(val))

    def _load_artifact(self):
        raw = self._load("active_artifact")
        if isinstance(raw, dict):
            data = raw
        else:
            try:
                data = json.loads(raw) if raw else None
            except (TypeError, ValueError):
                return None
        if not isinstance(data, dict) or not data.get("path"):
            return None
        related = data.get("related_paths") or []
        data["related_paths"] = [str(item) for item in related if item][-20:]
        return data

    def get_artifact(self):
        artifact = self.active_artifact or self._load_artifact()
        self.active_artifact = artifact
        if not artifact:
            return None
        path = artifact.get("path")
        if not path or not os.path.exists(path):
            return None
        return artifact

    def set_artifact(self, path=None, language=None, kind=None, query=None, request=None, related_paths=None, extra=None):
        previous = self.active_artifact or {}
        related = list(previous.get("related_paths") or [])
        if related_paths:
            related.extend(str(item) for item in related_paths if item)
        if previous.get("path") and previous.get("path") != path and previous.get("path") not in related:
            related.append(previous.get("path"))
        if path:
            path = os.path.abspath(path)
            self.last_path = path
            self._save("last_path", path)
        now = time.time()
        artifact = {
            "path": path or previous.get("path"),
            "language": language or previous.get("language"),
            "kind": kind or previous.get("kind"),
            "query": query if query is not None else previous.get("query"),
            "request": request if request is not None else previous.get("request"),
            "related_paths": related[-20:],
            "created_at": previous.get("created_at") or now,
            "updated_at": now,
        }
        if isinstance(extra, dict):
            artifact.update(extra)
        self.active_artifact = artifact
        self._save("active_artifact", json.dumps(artifact))
        return artifact

    def set_browser_open(self, browser_name: str):
        """Mark a browser as currently open and active."""
        self.browser_open = True
        self.active_browser = browser_name.lower()
        self._save("active_browser", self.active_browser)

    def clear_browser_open(self):
        self.browser_open = False
        self.active_browser = ""
        self._save("active_browser", "")

    def update(self, cmd=None, app=None, query=None, browser=None, screenshot=None, url=None, selector=None, engine=None, yt_query=None, last_path=None, last_response=None, active_document=None, last_search=None, current_topic=None, active_goal=None, last_sdd=None, **kwargs):
        # Update session timer to prevent premature context expiration during active tasks
        self.session_time = time.time()
        self._save("session_time", self.session_time)
        for k, v in kwargs.items():
            setattr(self, k, v)
            if v is not None:
                self._save(k, v)

        if cmd:
            self.last_cmd = cmd
            self._save("last_cmd", cmd)
        if app:
            self.last_app = app
            self._save("last_app", app)
        if query:
            self.last_query = query
            self._save("last_query", query)
        if browser:
            self.last_browser = browser
            self._save("last_browser", browser)
        if screenshot:
            self.last_screenshot = screenshot
            self._save("last_screenshot", screenshot)
        if url:
            self.last_url = url
            self._save("last_url", url)
        if selector:
            self.last_selector = selector
            self._save("last_selector", selector)
        if engine:
            self.active_engine = engine
            self._save("active_engine", engine)
        if yt_query:
            self.last_yt_query = yt_query
            self._save("last_yt_query", yt_query)
        if last_path:
            self.last_path = last_path
            self._save("last_path", last_path)
        if last_response:
            self.last_response = last_response
            self.last_generated_content = last_response
            self._save("last_response", last_response)
        if active_document:
            self.active_document = active_document
            self._save("active_document", active_document)
        if last_search:
            self.last_search = last_search
            self._save("last_search", last_search)
        if current_topic:
            self.current_topic = current_topic
            self._save("current_topic", current_topic)
        if active_goal:
            self.active_goal = active_goal
            self._save("active_goal", active_goal)
        if last_sdd is not None:
            self.last_sdd = last_sdd
            self._save("last_sdd", last_sdd)

        # Always synchronize system states during memory updates
        self.sync_system_state()

    @staticmethod
    def _leading_action(text):
        token = (text or "").split(" ", 1)[0].strip()
        return token if re.fullmatch(r"[a-z]+", token or "") else ""

    def _artifact_command(self, cmd, reference):
        artifact = self.get_artifact()
        if not artifact:
            return None
        action = self._leading_action(reference)
        remainder = reference[len(action):].strip() if action else reference
        if not action:
            return None
        basename = os.path.basename(str(artifact.get("path") or "")).lower()
        explicit_names = [token.lower() for token in re.findall(r"[\w.-]+\.[\w]{1,10}", remainder)]
        if explicit_names and all(name != basename for name in explicit_names):
            return None
        has_pronoun = bool(re.search(r"\b(that|it|this)\b", reference))
        mentions_work = bool(re.search(r"\b(files?|pages?|documents?|code|apps?|projects?|programs?|scripts?|html|css|js)\b", reference))
        change_noun = bool(re.search(r"\b(changes?|updates?|modifications?|revisions?|fixes?|improvements?)\b", remainder))
        open_verbs = {"open", "show", "display", "preview", "launch", "start"}
        run_verbs = {"run", "execute", "test"}
        edit_verbs = {"edit", "change", "update", "modify", "revise", "fix", "improve", "enhance", "add", "insert", "append"}
        create_verbs = {"create", "generate", "build", "make", "write", "design", "develop"}
        linked_markers = {"another", "new", "second", "other", "next", "linked", "redirect", "redirects", "navigate", "navigation", "route", "link", "links", "connect", "connected"}
        if action in open_verbs and (has_pronoun or mentions_work):
            return f"artifact_open:{cmd}"
        if action in run_verbs and (has_pronoun or mentions_work):
            return f"artifact_run:{cmd}"
        if action in edit_verbs and (has_pronoun or mentions_work or change_noun):
            return f"artifact_edit:{cmd}"
        if action == "make" and change_noun:
            return f"artifact_edit:{cmd}"
        if action in create_verbs and has_pronoun and not linked_markers.intersection(set(reference.split())):
            return f"artifact_edit:{cmd}"
        if action in create_verbs and mentions_work and linked_markers.intersection(set(reference.split())):
            return f"artifact_extend:{cmd}"
        return None

    def resolve(self, cmd: str) -> str:
        # Re-sync system focus and clipboard state before resolving to ensure we use latest context
        self.sync_system_state()

        if time.time() - self.session_time > self.session_duration:
            self.clear_session()
            return cmd

        c = cmd.lower().strip()
        reference = re.sub(r"^(please|can you|could you|would you|will you|do you)\s+", "", c).strip()
        reference = re.sub(r"\s+for\s+me$", "", reference).strip()

        # Check for pending actions first (multi-turn conversations)
        if self.pending_action:
            # Return the command as-is so the handler can process the follow-up
            return cmd

        artifact_command = self._artifact_command(cmd, reference)
        if artifact_command:
            return artifact_command

        # Match paste/write commands for registers
        for reg_name, val in list(self.registers.items()):
            if c in [f"paste the {reg_name} register", f"paste {reg_name} register", f"write the {reg_name} register", f"type the {reg_name} register"]:
                self.last_response = val
                return "paste_context_response"

        # Dialogue Continuation Phrase Matching (e.g., "add two points to that", "continue with that")
        continuation_patterns = [
            r"add (?:two|three|some|more)?\s*(?:points|details|lines|content|text)?\s*(?:to|onto)\s*(?:that|it|this)",
            r"continue\s*(?:with|on)?\s*(?:that|it|this|that task|the active task)",
            r"elaborate\s*(?:on)?\s*(?:that|it|this)"
        ]
        for pattern in continuation_patterns:
            if re.search(pattern, c):
                # Map to a special internal command that handles dialogue/document continuation
                return f"continue_context_query:{cmd}"

        # References dictionary mapping for seamless workflow routing
        if any(x == c for x in ["paste it", "paste the answer", "paste answer", "write it", "write the answer", "write that in the file", "write that", "paste that", "paste it there", "paste that there", "write that there", "write it there", "type it", "type that", "paste response", "paste it here", "paste that here"]) or \
           re.search(r"\b(paste|type)\b.*\b(result|response|answer|that|it)\b.*\b(document|file|notepad|editor|here|there)\b", c) or \
           re.search(r"\b(paste|type)\b.*\b(result|response|answer)\b", c) or \
           re.search(r"\bwrite\b.*\b(result|response|answer|that|it)\b", c):
            return "paste_context_response"

        # "copy that", "copy the answer", "copy it"
        if any(x == c for x in ["copy that", "copy the answer", "copy it", "copy answer"]):
            return "copy_context_response"

        # "save it", "save that", "save the document"
        if any(x == c for x in ["save it", "save that", "save the document"]):
            return "save_active_context_file"

        # Delete / Remove Pronoun Resolution
        if any(x == c for x in ["delete it", "delete that", "delete this file", "remove it", "remove that", "delete the file", "delete that file", "delete the folder", "delete that folder", "erase it", "erase that"]):
            target = self.active_document or self.last_path
            if target and os.path.exists(target):
                if os.path.isdir(target):
                    return f"delete folder {target}"
                else:
                    return f"delete file {target}"

        # Rename Pronoun Resolution (e.g. "rename it to test.txt")
        rename_match = re.search(r"^(rename it|rename that|rename the file|rename the folder|change its name)\s+(?:to|as)\s+(.+)$", c)
        if rename_match:
            target = self.active_document or self.last_path
            if target and os.path.exists(target):
                new_name = rename_match.group(2).strip()
                return f"rename {target} to {new_name}"

        # Browser interactive pronoun resolution
        if c.startswith("fill it with ") or (c.startswith("type ") and c.endswith(" in it")):
            if self.last_selector:
                val = ""
                if c.startswith("fill it with "):
                    val = c.replace("fill it with ", "").strip()
                elif c.startswith("type ") and c.endswith(" in it"):
                    val = c[5:-6].strip()
                return f"type in {self.last_selector} with {val}"

        if c in ["click it", "click that", "click on it"] or " click it" in c or "click that" in c:
            if self.last_selector:
                return f"click {self.last_selector}"
        if "play it again" in c or "open it again" in c:
            if self.last_url:
                return f"navigate to {self.last_url}"
        if any(x == c for x in ["show it again", "show that again"]) and self.last_screenshot:
            return "show screenshot"
        if any(x == reference for x in ["open it", "open that", "open this", "open the file", "open this file", "open that file", "open the folder", "open that folder", "open this folder", "open the directory", "open it again"]):
            target_file = self.active_document or self.last_path or self.last_screenshot
            if target_file:
                return f"open {target_file}"
        if any(x == c for x in ["close it", "close that", "close this", "close the app", "close the window", "close that window", "close this window", "close this app"]):
            # Use focused window if available, fallback to cached last app
            app_to_close = None
            if self.focused_app and self.focused_app != "Unknown":
                # Extract first word of window title as target app
                app_to_close = self.focused_app.split()[0].strip()
            if not app_to_close:
                app_to_close = self.last_app
            if app_to_close:
                return f"close {app_to_close}"
        if any(x == c for x in ["search more about that", "search more about it", "search about it", "tell me more about it", "explain it further", "explain that"]):
            if self.last_query:
                return f"what is {self.last_query}"

        # Identify complex context-aware writing intents pointing to opened files/documents
        c_clean = c
        is_write_to_file = False
        for keyword in ["in that opened document", "in that document", "in the document", "in that file", "in the file", "in that opened file", "in document"]:
            if keyword in c_clean:
                is_write_to_file = True
                c_clean = c_clean.replace(keyword, "").strip()
                break

        if c_clean.startswith("in that file") or c_clean.startswith("in the file") or c_clean.startswith("in the document"):
            is_write_to_file = True
            c_clean = c_clean.replace("in that file", "").replace("in the file", "").replace("in the document", "").strip()

        if is_write_to_file:
            # Strip prefixes like "ok", "write", "paste", "insert", "add", "type", "right"
            for prefix in ["ok", "write", "paste", "insert", "add", "type", "right"]:
                c_clean = re.sub(r"^" + prefix + r"\b", "", c_clean).strip()
            if len(c_clean) > 3:
                return f"write_context_query:{c_clean}"

        return cmd
