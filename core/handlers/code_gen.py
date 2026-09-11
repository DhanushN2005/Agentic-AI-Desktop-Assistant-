import re
import os
from utils.path_resolver import PathResolver
from utils.config import Config


def handle_code_gen(orch, c):
    """Generate code based on query, optionally save to file."""
    # Parse query and save location
    query, save_path, language = _parse_code_query(c)

    if not query:
        orch.speak("What code would you like me to generate?")
        return True

    orch.send_to_ui("STATE", "PROCESSING")

    # Step 1: Generate code using LLM
    orch.speak(f"Generating {language} code for {query}...")

    prompt = f"""Generate clean, well-commented {language} code for: {query}

Requirements:
1. Include proper error handling
2. Add clear comments explaining the logic
3. Use best practices and conventions
4. Include a main block or example usage if applicable
5. Make the code production-ready

Return ONLY the code, no explanations outside the code."""

    code = orch.brain.ask(prompt, system_override="You are an expert programmer. Generate clean, well-commented code. Return ONLY the code. Do not use any tools or functions - just return the raw code text.")

    if not code:
        orch.speak("I couldn't generate the code. Please try again.")
        return True

    # Clean up the code (remove markdown code blocks if present)
    code = _clean_code(code)

    # Step 2: Save to file if requested
    if save_path:
        try:
            resolver = PathResolver()
            file_path = resolver.resolve(save_path)

            # Ensure the directory exists
            os.makedirs(file_path, exist_ok=True)

            # Generate filename from query
            filename = _generate_filename(query, language)
            full_path = os.path.join(file_path, filename)

            # Write the code
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(code)

            orch.speak(f"Code saved to {full_path}")
            orch.ctx.update(last_path=full_path, last_response=code)
        except Exception as e:
            orch.speak(f"Error saving file: {str(e)}")
    else:
        # Just display/speak the code
        orch.speak(f"Here's the {language} code for {query}")
        orch.ctx.update(last_response=code, last_query=query)

    return True


def _parse_code_query(c):
    """Extract code query, save location, and language from command."""
    cmd = c.lower().strip()
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

    # Simple approach: find "save to X" or "save in X" at the end
    save_match = re.search(r"save\s+(?:to|in|into)\s+(?:the\s+)?(\w+)\s*$", cmd, re.IGNORECASE)
    if save_match:
        save_path = save_match.group(1)
        # Remove everything from "save" onwards
        query = cmd[:save_match.start()].strip()
    else:
        # Check for "save to X" anywhere
        save_match = re.search(r"save\s+(?:to|in|into)\s+(?:the\s+)?(\w+)", cmd, re.IGNORECASE)
        if save_match:
            save_path = save_match.group(1)
            # Remove the save part
            query = cmd[:save_match.start()].strip()
        else:
            # Check for "save the code" or "save it" pattern (with optional language keyword)
            save_match = re.search(r"save\s+(?:the\s+)?(?:\w+\s+)?(?:code|script|program|file|result|output|it)\s*$", cmd, re.IGNORECASE)
            if save_match:
                # No specific path mentioned, will use default
                query = cmd[:save_match.start()].strip()
            else:
                query = cmd

    # Remove code generation prefixes
    query = re.sub(r"^(tell|give|show|write|generate|create|get|find)\s+(?:me\s+)?", "", query, flags=re.IGNORECASE)
    query = re.sub(r"^(a|the|an|my|some)\s+", "", query, flags=re.IGNORECASE)

    # Clean up the query - remove language keywords and code-related words
    query = re.sub(r"\b(code|script|program|implementation|algorithm|function|class|from online|from the web)\b", "", query, flags=re.IGNORECASE)
    # Remove language keywords from query
    for lang_word in ["python", "java", "javascript", "js", "c++", "cpp", "html", "css", "sql", "ruby", "go", "rust", "swift", "kotlin"]:
        query = re.sub(r"\b" + re.escape(lang_word) + r"\b", "", query, flags=re.IGNORECASE)
    # Remove trailing connecting words
    query = re.sub(r"\s+(and|or|the|a|an|my|from|with|for)\s*$", "", query, flags=re.IGNORECASE)
    query = re.sub(r"^(and|or|the|a|an|my|from|with|for)\s+", "", query, flags=re.IGNORECASE)
    query = re.sub(r"\s+", " ", query).strip()

    # If no save path detected, check if the user mentioned downloads/desktop/documents anywhere
    if not save_path:
        if re.search(r"\b(downloads?|desktop|documents?)\b", cmd, re.IGNORECASE):
            match = re.search(r"\b(downloads?|desktop|documents?)\b", cmd, re.IGNORECASE)
            save_path = match.group(1)
        elif re.search(r"\bsave\b", cmd, re.IGNORECASE):
            # User said "save" but no location -> default to Downloads
            save_path = "downloads"

    return query, save_path, language


def _clean_code(code):
    """Remove markdown code blocks and clean up the code."""
    # Remove markdown code blocks
    code = re.sub(r"```(?:\w+)?\n(.*?)\n```", r"\1", code, flags=re.DOTALL)
    code = re.sub(r"```", "", code)

    # Remove leading/trailing whitespace
    code = code.strip()

    return code


def _generate_filename(query, language):
    """Generate a filename from the code query."""
    # Clean the query to make a valid filename
    clean = re.sub(r'[^\w\s-]', '', query.lower())
    clean = re.sub(r'[-\s]+', '_', clean).strip('_')[:30]
    if not clean or clean in ('', '_'):
        clean = 'generated_code'

    # Map language to extension
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

    ext = extensions.get(language, ".py")
    return f"{clean}{ext}"
