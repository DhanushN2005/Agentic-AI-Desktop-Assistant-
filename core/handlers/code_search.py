"""
Local Code Search Handler — searches the local codebase for code patterns.
"""
import re
import os
from utils.path_resolver import PathResolver


def handle_local_code_search(orch, c, silent=False):
    """
    Handle local code search commands.
    
    Examples:
        "search my code for binary search"
        "find function binary_search"
        "search project for algorithm"
        "find class SearchEngine"
    """
    from engines.code_search import CodeSearchEngine
    
    cmd = c.lower().strip()
    
    # Initialize code search engine with workspace
    workspace = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    engine = CodeSearchEngine(workspace_path=workspace)
    
    # Extract search query
    query = None
    search_type = "text"
    
    # Pattern: "find function <name>"
    func_match = re.search(r"find\s+function\s+(\w+)", cmd)
    if func_match:
        query = func_match.group(1)
        search_type = "function"
    
    # Pattern: "find class <name>"
    class_match = re.search(r"find\s+class\s+(\w+)", cmd)
    if class_match:
        query = class_match.group(1)
        search_type = "class"
    
    # Pattern: "search for <query>" or "search code for <query>"
    if not query:
        search_match = re.search(r"search\s+(?:my\s+)?(?:the\s+)?(?:code\s+)?(?:for\s+)?(.+?)(?:\s+and\s+.+)?$", cmd)
        if search_match:
            query = search_match.group(1).strip()
    
    # Pattern: "find <query> in code/project"
    if not query:
        find_match = re.search(r"find\s+(.+?)(?:\s+in\s+(?:my\s+)?(?:the\s+)?(?:code|project|codebase))", cmd)
        if find_match:
            query = find_match.group(1).strip()
    
    # Pattern: "grep for <query>"
    if not query:
        grep_match = re.search(r"grep\s+for\s+(.+)", cmd)
        if grep_match:
            query = grep_match.group(1).strip()
    
    if not query:
        orch.speak("What would you like me to search for in your code?")
        return True
    
    # Clean up query — remove common suffixes
    query = re.sub(r"\s+and\s+.+$", "", query).strip()
    
    if not silent:
        orch.speak(f"Searching your code for {query}...")
    
    # Perform search based on type
    if search_type == "function":
        results = engine.find_function(query, max_results=10)
    elif search_type == "class":
        results = engine.find_class(query, max_results=10)
    else:
        # Extract file extensions if specified
        extensions = None
        ext_match = re.search(r"in\s+(\w+)\s+files?", cmd)
        if ext_match:
            ext_name = ext_match.group(1).lower()
            ext_map = {"python": [".py"], "javascript": [".js"], "typescript": [".ts"], "java": [".java"]}
            extensions = ext_map.get(ext_name)
        
        results = engine.search(query, extensions=extensions, max_results=10)
    
    # Process results
    if results.total_matches == 0:
        orch.speak(f"I couldn't find any matches for '{query}' in your codebase.")
        # Store for potential follow-up
        orch.ctx.update(
            last_response=f"No matches found for '{query}'",
            last_search=query,
            active_engine="code_search"
        )
        return True
    
    # Format response
    response_parts = [f"Found {results.total_matches} match{'es' if results.total_matches != 1 else ''} for '{query}':"]
    
    for i, match in enumerate(results.matches[:5], 1):
        response_parts.append(f"{i}. {match.file} (line {match.line_start}) — {match.match_type}")
        # Show first line of content
        first_line = match.content.split('\n')[0][:100]
        response_parts.append(f"   {first_line}")
    
    if results.total_matches > 5:
        response_parts.append(f"... and {results.total_matches - 5} more matches.")
    
    response = "\n".join(response_parts)
    
    if not silent:
        orch.speak(response)
    
    # Store results in context for follow-up
    orch.ctx.update(
        last_response=response,
        last_search=query,
        active_engine="code_search",
        last_path=results.matches[0].file if results.matches else ""
    )
    
    return True
