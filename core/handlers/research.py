import re
import urllib.parse
import webbrowser
from utils.path_resolver import PathResolver
from utils.config import Config


def handle_research(orch, c):
    """Research a topic via web search, get LLM summary, optionally save to file."""
    # Extract query and save location
    query, save_path = _parse_research_query(c)

    if not query:
        orch.speak("What would you like me to research?")
        return True

    orch.send_to_ui("STATE", "PROCESSING")

    # Step 1: Search the web
    orch.speak(f"Researching {query}...")
    search_results = _web_search(query)

    # Step 2: Get comprehensive summary from LLM
    prompt = f"""You are a research assistant providing detailed information. Provide a COMPREHENSIVE summary about: {query}

Web search results for reference:
{search_results}

IMPORTANT: Your response MUST be at least 300 words (about 10-15 lines of text). Do NOT be brief.

Structure your response with these sections:

## Definition & Overview
What is {query}? Provide a clear, detailed definition.

## How It Works / Key Principles
Explain the process, mechanism, or fundamental principles.

## Important Facts & Statistics
Include key data points, numbers, dates, or statistics.

## Real-World Examples
Provide concrete examples of how it's used or applied.

## Benefits & Advantages
Why is it important? What are the key benefits?

## Key Takeaways
Bullet point summary of the most important points.

Write in a clear, informative style. Use headings and bullet points for readability. MINIMUM 300 words."""

    # Use a custom system prompt for research to allow longer responses
    summary = orch.brain.ask(prompt, system_override="You are a research assistant. Provide detailed, comprehensive responses with at least 300 words. Do NOT be brief. Do not use any tools or functions - just return the text response.")

    if not summary:
        orch.speak("I couldn't find enough information about that topic.")
        return True

    # Step 3: Save to file if requested
    if save_path:
        try:
            resolver = PathResolver()
            file_path = resolver.resolve(save_path)

            # Ensure the directory exists
            import os
            os.makedirs(file_path, exist_ok=True)

            # Generate filename from query
            filename = _generate_filename(query)
            full_path = os.path.join(file_path, filename)

            # Write the content
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(f"Research: {query}\n")
                f.write("=" * 60 + "\n\n")
                f.write(summary)

            orch.speak(f"Research saved to {full_path}")
            orch.ctx.update(last_path=full_path, last_response=summary)
        except Exception as e:
            orch.speak(f"Error saving file: {str(e)}")
    else:
        # Just display/speak the result
        orch.speak(summary)
        orch.ctx.update(last_response=summary, last_query=query)

    return True


def _parse_research_query(c):
    """Extract research query and save location from command."""
    cmd = c.lower().strip()
    query = None
    save_path = None

    # Pattern: "research X and save to Y"
    save_patterns = [
        r"and\s+save\s+(?:the\s+)?(?:result|output|content|information|answer)?\s*(?:to|in|into)\s+(?:the\s+)?(.+?)(?:\s*$)",
        r"save\s+(?:the\s+)?(?:result|output|content|information|answer)?\s*(?:to|in|into)\s+(?:the\s+)?(.+?)(?:\s*$)",
        r"export\s+(?:the\s+)?(?:result|output|answer)?\s*(?:to|as)\s+(?:the\s+)?(.+?)(?:\s*$)",
    ]

    for pattern in save_patterns:
        match = re.search(pattern, cmd, re.IGNORECASE)
        if match:
            save_path = match.group(1).strip()
            # Remove the save part from the command to get the query
            query = re.split(pattern, cmd, flags=re.IGNORECASE)[0].strip()
            break

    if not query:
        # Remove research prefixes
        query = re.sub(r"^(research|look up|find out|google|search the web for|search online for|search the internet for)\s+", "", cmd, flags=re.IGNORECASE)

    # Clean up common prefixes
    query = re.sub(r"^(about|on|for)\s+", "", query, flags=re.IGNORECASE)

    return query, save_path


def _web_search(query):
    """Perform a web search and return results."""
    try:
        import requests
        from bs4 import BeautifulSoup

        # Use DuckDuckGo HTML search (no API key needed)
        url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote_plus(query)}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, "html.parser")

        results = []
        for result in soup.select(".result")[:5]:
            title_el = result.select_one(".result__a")
            snippet_el = result.select_one(".result__snippet")

            if title_el and snippet_el:
                title = title_el.get_text(strip=True)
                snippet = snippet_el.get_text(strip=True)
                results.append(f"{title}\n{snippet}")

        if results:
            return "\n\n".join(results)
        else:
            # Fallback: Use LLM to generate information
            return _fallback_search(query)

    except Exception:
        return _fallback_search(query)


def _fallback_search(query):
    """Fallback search using LLM when web search fails."""
    try:
        from core.brain import Brain
        brain = Brain()
        return brain.ask(f"Provide key facts and information about: {query}. Be concise but comprehensive.")
    except Exception:
        return f"Information about {query} (web search unavailable)"


def _generate_filename(query):
    """Generate a filename from the research query."""
    # Clean the query to make a valid filename
    clean = re.sub(r'[^\w\s-]', '', query.lower())
    clean = re.sub(r'[-\s]+', '_', clean)[:50]
    return f"research_{clean}.txt"
