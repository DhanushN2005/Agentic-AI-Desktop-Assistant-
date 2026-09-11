"""
Code Search Engine — local codebase search with structured results.

Searches the project workspace for code patterns, function definitions,
class definitions, and text matches. Returns structured results with
file paths, line numbers, and content snippets.
"""
import os
import re
import logging
from typing import List, Dict, Optional
from dataclasses import dataclass, field


@dataclass
class CodeMatch:
    """A single code match result."""
    file: str
    line_start: int
    line_end: int
    content: str
    language: str = ""
    match_type: str = "text"  # "text", "function", "class", "symbol"

    def to_dict(self) -> dict:
        return {
            "file": self.file,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "content": self.content,
            "language": self.language,
            "match_type": self.match_type,
        }


@dataclass
class SearchResult:
    """Aggregated search results."""
    query: str
    matches: List[CodeMatch] = field(default_factory=list)
    total_matches: int = 0
    search_paths: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "matches": [m.to_dict() for m in self.matches],
            "total_matches": self.total_matches,
            "search_paths": self.search_paths,
        }


# File extensions to search
CODE_EXTENSIONS = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "javascript",
    ".tsx": "typescript",
    ".java": "java",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".scala": "scala",
    ".sh": "shell",
    ".bash": "shell",
    ".ps1": "powershell",
    ".bat": "batch",
    ".cmd": "batch",
    ".sql": "sql",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".less": "less",
    ".json": "json",
    ".xml": "xml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".ini": "ini",
    ".cfg": "config",
    ".conf": "config",
    ".md": "markdown",
    ".txt": "text",
    ".rst": "rst",
    ".vue": "vue",
    ".svelte": "svelte",
}

# Directories to skip
SKIP_DIRS = {
    ".git", ".svn", ".hg", "__pycache__", "node_modules", ".venv", "venv",
    "env", ".env", "dist", "build", ".tox", ".eggs", "*.egg-info",
    ".mypy_cache", ".pytest_cache", ".idea", ".vscode",
}


class CodeSearchEngine:
    """
    Searches the local codebase for code patterns.
    
    Usage:
        engine = CodeSearchEngine(workspace_path="E:\\HACKATHON\\flexiee\\flexie_v2")
        results = engine.search("binary search")
        results = engine.find_function("binary_search")
        results = engine.find_class("SearchEngine")
    """

    def __init__(self, workspace_path: Optional[str] = None):
        self.logger = logging.getLogger("Flexie.CodeSearch")
        if workspace_path:
            self.workspace = workspace_path
        else:
            # Default to project root
            self.workspace = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def search(
        self,
        query: str,
        extensions: Optional[List[str]] = None,
        max_results: int = 50,
        context_lines: int = 2,
    ) -> SearchResult:
        """
        Search for text patterns in the codebase.
        
        Args:
            query: Search query (supports regex)
            extensions: File extensions to search (e.g., [".py", ".js"]). None = all code files.
            max_results: Maximum number of results
            context_lines: Lines of context around each match
        
        Returns:
            SearchResult with structured matches
        """
        result = SearchResult(query=query, search_paths=[self.workspace])
        
        try:
            pattern = re.compile(query, re.IGNORECASE)
        except re.error:
            # If regex is invalid, use literal search
            pattern = re.compile(re.escape(query), re.IGNORECASE)

        searched = 0
        for root, dirs, files in os.walk(self.workspace):
            # Skip excluded directories
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
            
            for fname in files:
                ext = os.path.splitext(fname)[1].lower()
                if extensions and ext not in extensions:
                    continue
                if ext not in CODE_EXTENSIONS:
                    continue
                    
                filepath = os.path.join(root, fname)
                rel_path = os.path.relpath(filepath, self.workspace)
                
                try:
                    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()
                    
                    for i, line in enumerate(lines):
                        if pattern.search(line):
                            # Get context
                            start = max(0, i - context_lines)
                            end = min(len(lines), i + context_lines + 1)
                            content = "".join(lines[start:end])
                            
                            match = CodeMatch(
                                file=rel_path,
                                line_start=i + 1,
                                line_end=end,
                                content=content.strip(),
                                language=CODE_EXTENSIONS.get(ext, "unknown"),
                                match_type="text",
                            )
                            result.matches.append(match)
                            result.total_matches += 1
                            
                            if len(result.matches) >= max_results:
                                return result
                except Exception as e:
                    self.logger.debug(f"[CODE_SEARCH] Error reading {filepath}: {e}")

        return result

    def find_function(
        self,
        name: str,
        extensions: Optional[List[str]] = None,
        max_results: int = 20,
    ) -> SearchResult:
        """Find function definitions by name."""
        # Match Python: def function_name(
        # Match JS/TS: function function_name( or const function_name = or function_name(
        escaped = re.escape(name)
        def_pattern = r"\bdef\s+" + escaped + r"\s*\("
        func_pattern = r"\bfunction\s+" + escaped + r"\s*\("
        assign_pattern = r"\b" + escaped + r"\s*=\s*(?:function|lambda|\()"
        
        combined = "|".join([def_pattern, func_pattern, assign_pattern])
        result = self.search(combined, extensions=extensions, max_results=max_results)
        result.query = f"function:{name}"
        
        # Mark as function matches
        for match in result.matches:
            match.match_type = "function"
        
        return result

    def find_class(
        self,
        name: str,
        extensions: Optional[List[str]] = None,
        max_results: int = 20,
    ) -> SearchResult:
        """Find class definitions by name."""
        patterns = [
            rf"\bclass\s+{re.escape(name)}\s*[\(:]",
            rf"\bclass\s+{re.escape(name)}\s*$",
        ]
        
        combined = "|".join(patterns)
        result = self.search(combined, extensions=extensions, max_results=max_results)
        result.query = f"class:{name}"
        
        for match in result.matches:
            match.match_type = "class"
        
        return result

    def find_symbol(
        self,
        name: str,
        extensions: Optional[List[str]] = None,
        max_results: int = 30,
    ) -> SearchResult:
        """Find any symbol (function, class, variable) by name."""
        pattern = rf"\b{re.escape(name)}\b"
        result = self.search(pattern, extensions=extensions, max_results=max_results)
        result.query = f"symbol:{name}"
        return result

    def read_file(self, filepath: str, start_line: int = 1, end_line: Optional[int] = None) -> str:
        """Read content from a file, optionally with line range."""
        # Handle both absolute and relative paths
        if not os.path.isabs(filepath):
            filepath = os.path.join(self.workspace, filepath)
        
        if not os.path.exists(filepath):
            return f"File not found: {filepath}"
        
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            
            if end_line is None:
                end_line = len(lines)
            
            content = "".join(lines[start_line - 1:end_line])
            return content
        except Exception as e:
            return f"Error reading file: {e}"
