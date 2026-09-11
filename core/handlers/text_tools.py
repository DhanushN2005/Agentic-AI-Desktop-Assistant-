import re


def handle_text_tools(orch, c):
    """Handle text manipulation commands."""
    orch.send_to_ui("STATE", "PROCESSING")
    cmd = c.lower().strip()
    cmd = re.sub(r"^(flexi|flexie|hey flexie|ok flexie)\b", "", cmd).strip()

    # Extract text from quotes or after command
    text = re.sub(r"^(word count|character count|count words|count chars|reverse|uppercase|lowercase|title case|sentence case|snake case|camel case|kebab case|remove duplicate|sort lines|slugify|wrap|extract emails|extract urls|extract numbers|find and replace)\s*", "", cmd, flags=re.IGNORECASE).strip()
    # Try to get text in quotes
    quote_match = re.search(r'["\'](.+?)["\']', cmd)
    if quote_match:
        text = quote_match.group(1)

    if not text and "count" not in cmd and "extract" not in cmd:
        orch.speak("What text should I process? Put it in quotes.")
        return True

    if "word count" in cmd or "count words" in cmd:
        response = orch.text_tools.word_count(text)
    elif "character count" in cmd or "count chars" in cmd:
        response = orch.text_tools.char_count(text)
    elif "reverse" in cmd:
        response = orch.text_tools.reverse(text)
    elif "uppercase" in cmd:
        response = orch.text_tools.uppercase(text)
    elif "lowercase" in cmd:
        response = orch.text_tools.lowercase(text)
    elif "title case" in cmd:
        response = orch.text_tools.title_case(text)
    elif "sentence case" in cmd:
        response = orch.text_tools.sentence_case(text)
    elif "snake case" in cmd:
        response = orch.text_tools.snake_case(text)
    elif "camel case" in cmd:
        response = orch.text_tools.camel_case(text)
    elif "kebab case" in cmd:
        response = orch.text_tools.kebab_case(text)
    elif "remove duplicate" in cmd:
        response = orch.text_tools.remove_duplicates(text)
    elif "sort lines" in cmd:
        response = orch.text_tools.sort_lines(text)
    elif "slugify" in cmd:
        response = orch.text_tools.slugify(text)
    elif "wrap" in cmd:
        width_match = re.search(r"wrap\s*(?:at\s*)?(\d+)", cmd)
        width = int(width_match.group(1)) if width_match else 80
        response = orch.text_tools.wrap(text, width)
    elif "extract emails" in cmd:
        response = orch.text_tools.extract_emails(text)
    elif "extract urls" in cmd:
        response = orch.text_tools.extract_urls(text)
    elif "extract numbers" in cmd:
        response = orch.text_tools.extract_numbers(text)
    else:
        response = orch.text_tools.word_count(text)

    orch.ctx.update(last_response=response, query=c)
    orch.speak(response)
    return True
