import re


def handle_lorem(orch, c):
    """Handle lorem ipsum generation commands."""
    orch.send_to_ui("STATE", "PROCESSING")
    cmd = c.lower().strip()
    cmd = re.sub(r"^(flexi|flexie|hey flexie|ok flexie)\b", "", cmd).strip()

    if "list" in cmd or "numbered" in cmd:
        count_match = re.search(r"(\d+)", cmd)
        count = int(count_match.group(1)) if count_match else 5
        response = orch.lorem.generate_list(count)
    elif "words" in cmd:
        count_match = re.search(r"(\d+)", cmd)
        count = int(count_match.group(1)) if count_match else 100
        response = orch.lorem.generate_words(count)
    else:
        para_match = re.search(r"(\d+)\s*(?:paragraph|para)", cmd)
        paragraphs = int(para_match.group(1)) if para_match else 3
        response = orch.lorem.generate(paragraphs)

    orch.ctx.update(last_response=response, query=c)
    orch.speak(f"Generated {len(response)} characters of lorem ipsum text.")
    return True
