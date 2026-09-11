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
from typing import Optional


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
        resolver = PathResolver(workspace="E:\\HACKATHON\\flexiee\\flexie_v2")
        path = resolver.resolve("Downloads folder")
        path = resolver.resolve("desktop")
        path = resolver.resolve("./output/result.py")
    """

    def __init__(self, workspace: Optional[str] = None):
        self.workspace = workspace or os.getcwd()
        self.home = Path.home()

    def resolve(self, path_str: str, default_extension: Optional[str] = None) -> str:
        """
        Resolve a natural language or relative path to an absolute path.
        
        Args:
            path_str: Natural language path or relative/absolute path
            default_extension: Extension to add if none specified (e.g., ".py")
        
        Returns:
            Resolved absolute path string
        """
        path_str = path_str.strip().lower()
        
        # Check for natural language folder references
        resolved = self._resolve_natural_language(path_str)
        if resolved:
            return resolved
        
        # Check for relative path with ~ expansion
        if "~" in path_str:
            return str(Path(path_str).expanduser())
        
        # Check for absolute path
        if os.path.isabs(path_str):
            return path_str
        
        # Relative path — resolve against workspace
        result = os.path.join(self.workspace, path_str)
        
        # Add extension if specified and not present
        if default_extension and not os.path.splitext(result)[1]:
            result += default_extension
        
        return result

    def _resolve_natural_language(self, path_str: str) -> Optional[str]:
        """Resolve natural language folder references."""
        path_lower = path_str.lower().strip()
        
        # Check exact matches first
        if path_lower in FOLDER_SUBPATHS:
            subpath = FOLDER_SUBPATHS[path_lower]
            return str(self.home / subpath)
        
        # Check partial matches
        for key, subpath in FOLDER_SUBPATHS.items():
            if key in path_lower:
                return str(self.home / subpath)
        
        # Check for "in the Downloads" pattern
        match = re.search(r"in\s+(?:the\s+)?(\w+)\s*(?:folder)?", path_lower)
        if match:
            folder_name = match.group(1)
            if folder_name in FOLDER_SUBPATHS:
                return str(self.home / FOLDER_SUBPATHS[folder_name])
        
        return None

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
