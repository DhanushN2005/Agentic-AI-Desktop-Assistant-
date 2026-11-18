import re


def handle_image_gen(orch, c):
    """Handle image generation commands (prompt keeps its original case)."""
    orch.send_to_ui("STATE", "PROCESSING")
    original = re.sub(r"^\s*(?:hey\s+|ok\s+)?(?:flexie|flexi)\b[\s,]*", "", c.strip(), flags=re.IGNORECASE).strip()

    prompt = re.sub(
        r"^(generate|create|make|draw|design|produce|show me)\s+(an?\s+)?"
        r"(image|picture|photo|pic|artwork|drawing|illustration)\s+(of\s+)?",
        "", original, flags=re.IGNORECASE,
    ).strip()
    if not prompt:
        prompt = original

    orch.speak(f"Generating image of {prompt}...")
    response = orch.image_gen.generate(prompt)
    orch.ctx.update(last_response=response, query=c)
    orch.speak(response)
    return True
