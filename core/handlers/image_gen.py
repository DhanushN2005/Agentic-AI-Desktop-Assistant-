import re


def handle_image_gen(orch, c):
    """Handle image generation commands."""
    orch.send_to_ui("STATE", "PROCESSING")
    cmd = c.lower().strip()
    cmd = re.sub(r"^(flexi|flexie|hey flexie|ok flexie)\b", "", cmd).strip()

    prompt = re.sub(r"^(generate|create|make|draw|design|produce|show me)\s+(an?\s+)?(image|picture|photo|pic|artwork|drawing|illustration)\s+(of\s+)?", "", cmd, flags=re.IGNORECASE).strip()
    if not prompt:
        prompt = cmd

    orch.speak(f"Generating image of {prompt}...")
    response = orch.image_gen.generate(prompt)
    orch.ctx.update(last_response=response, query=c)
    orch.speak(response)
    return True
