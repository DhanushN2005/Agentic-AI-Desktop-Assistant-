import re


def handle_color(orch, c):
    """Handle color information commands."""
    orch.send_to_ui("STATE", "PROCESSING")
    cmd = c.lower().strip()
    cmd = re.sub(r"^(flexi|flexie|hey flexie|ok flexie)\b", "", cmd).strip()

    if "random" in cmd:
        response = orch.color_info.random_color()
    elif "complementary" in cmd:
        hex_match = re.search(r"#?([0-9a-fA-F]{6})", cmd)
        if hex_match:
            response = orch.color_info.complementary(hex_match.group(1))
        else:
            response = "Provide a hex code like '#ff0000'."
    elif "hex" in cmd or "#" in cmd:
        hex_match = re.search(r"#?([0-9a-fA-F]{6})", cmd)
        if hex_match:
            response = orch.color_info.from_hex(hex_match.group(1))
        else:
            response = "Provide a hex code like '#ff0000'."
    else:
        color = re.sub(r"^(color|colour|look up|what is|info)\s*", "", cmd, flags=re.IGNORECASE).strip()
        if color:
            response = orch.color_info.lookup(color)
        else:
            response = orch.color_info.random_color()

    orch.ctx.update(last_response=response, query=c)
    orch.speak(response)
    return True
