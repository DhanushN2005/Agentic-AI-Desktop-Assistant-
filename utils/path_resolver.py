"""
Path Resolver — resolves natural language paths to actual filesystem paths.

Supports:
  "Downloads folder" → C:\\Users\\<user>\\Downloads
  "desktop" → C:\\Users\\<user>\\Desktop
  "documents" → C:\\Users\\<user>\\Documents
  "my project" → workspace root

Never hard-codes user-specific paths. Uses pathlib and os.path.expanduser.
"""
import os
import re
from pathlib import Path

# Windows known folder names to environment variables
KNOWN_FOLDERS = {
    "downloads": "USERPROFILE",
    "desktop": "USERPROFILE",
    "documents": "USERPROFILE",
    "pictures": "USERPROFILE",
    "music": "USERPROFILE",
    "videos": "USERPROFILE",
    "home": "USERPROFILE",
}

# Subfolder mappings
FOLDER_SUBPATHS = {
    "downloads": "Downloads",
    "desktop": "Desktop",
    "documents": "Documents",
    "pictures": "Pictures",
    "music": "Music",
    "videos": "Videos",
    "documents folder": "Documents",
    "downloads folder": "Downloads",
    "desktop folder": "Desktop",
    "my downloads": "Downloads",
    "my desktop": "Desktop",
    "my documents": "Documents",
}


class PathResolver:
    """
    Resolves natural language paths to actual filesystem paths.

    Usage:
        resolver = PathResolver()  # defaults to os.getcwd()
        resolver = PathResolver(workspace="/path/to/project")
        path = resolver.resolve("Downloads folder")
        path = resolver.resolve("desktop")
        path = resolver.resolve("./output/result.py")
    """

    def __init__(self, workspace: str | None = None):
        if workspace:
            self.workspace = workspace
        else:
            # Default to project root (parent of utils/), not cwd, so it works from any launch dir.
            self.workspace = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.home = Path.home()

    def resolve(self, path_str: str, default_extension: str | None = None) -> str:
        """
        Resolve a natural language or relative path to an absolute path.

        Args:
            path_str: Natural language path or relative/absolute path
            default_extension: Extension to add if none specified (e.g., ".py")

        Returns:
            Resolved absolute path string
        """
        path_str = (path_str or "").strip()

        # Known folder aliases are honoured only as the FIRST path component;
        # the remainder (file name, sub-folders, CASE) is preserved.
        resolved = self._resolve_natural_language(path_str)
        if resolved:
            if default_extension and not os.path.splitext(resolved)[1] and resolved != str(self.home):
                known = {str(self.home / v) for v in FOLDER_SUBPATHS.values()}
                if resolved not in known:
                    resolved += default_extension
            return resolved

        # Leading ~ expansion only
        if path_str.startswith("~"):
            return str(Path(path_str).expanduser())

        # Check for absolute path
        if os.path.isabs(path_str):
            return path_str

        # Relative path — resolve against workspace (case preserved)
        result = os.path.join(self.workspace, path_str)

        # Add extension if specified and not present
        if default_extension and not os.path.splitext(result)[1]:
            result += default_extension

        return result

    def _resolve_natural_language(self, path_str: str) -> str | None:
        """Resolve a leading known-folder alias ("downloads", "my desktop",
        "documents folder", "in the downloads folder") plus any remainder."""
        text = path_str.strip()
        parts = [p for p in re.split(r"[\\/]+", text) if p]
        if not parts:
            return None

        head = parts[0].strip().lower()
        rest = parts[1:]
        key = None
        if head in FOLDER_SUBPATHS:
            key = head
        else:
            m = re.fullmatch(r"in\s+(?:the\s+)?(\w+)(?:\s+folder)?", head)
            if m and m.group(1) in FOLDER_SUBPATHS:
                key = m.group(1)
        if key is None:
            return None
        return str(self.home.joinpath(FOLDER_SUBPATHS[key], *rest))

    def resolve_filename(self, filename: str, content_hint: str = "") -> str:
        """
        Resolve a filename, adding appropriate extension if missing.

        Args:
            filename: Filename (may or may not have extension)
            content_hint: Hint about content type (e.g., "python", "text", "json")

        Returns:
            Filename with appropriate extension
        """
        name, ext = os.path.splitext(filename)

        if ext:
            return filename

        # Determine extension from content hint
        ext_map = {
            "python": ".py",
            "py": ".py",
            "javascript": ".js",
            "js": ".js",
            "typescript": ".ts",
            "ts": ".ts",
            "json": ".json",
            "text": ".txt",
            "txt": ".txt",
            "html": ".html",
            "css": ".css",
            "markdown": ".md",
            "md": ".md",
            "code": ".py",  # Default code to Python
        }

        hint_lower = content_hint.lower()
        for key, extension in ext_map.items():
            if key in hint_lower:
                return filename + extension

        # Default to .txt for text content
        return filename + ".txt"

    def ensure_directory(self, path: str) -> str:
        """Ensure the directory exists, create if needed."""
        directory = os.path.dirname(path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)
        return path
