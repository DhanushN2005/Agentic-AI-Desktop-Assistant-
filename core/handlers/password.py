import re


def handle_password(orch, c):
    """Handle password generation commands."""
    orch.send_to_ui("STATE", "PROCESSING")
    cmd = c.lower().strip()
    cmd = re.sub(r"^(flexi|flexie|hey flexie|ok flexie)\b", "", cmd).strip()

    if "check" in cmd or "strength" in cmd or "evaluate" in cmd:
        pw_match = re.search(r"(?:check|strength|evaluate|how (?:strong|secure))\s+(?:the\s+)?(?:password\s+)?[\"']?(\S+)[\"']?", cmd)
        if pw_match:
            result = orch.password_gen.strength_check(pw_match.group(1))
            response = f"Password strength: {result['level']} (score {result['score']}/6)"
            if result["feedback"]:
                response += ". Tips: " + ", ".join(result["feedback"])
        else:
            response = "What password should I check?"
        orch.ctx.update(last_response=response, query=c)
        orch.speak(response)
        return True

    if "passphrase" in cmd:
        length_match = re.search(r"(\d+)\s*words?", cmd)
        words = int(length_match.group(1)) if length_match else 4
        response = orch.password_gen.generate_passphrase(words)
        orch.ctx.update(last_response=response, query=c)
        orch.speak(f"Here's your passphrase: {response}")
        return True

    length_match = re.search(r"(\d+)\s*(?:char|digit|letter|length|long)", cmd)
    length = int(length_match.group(1)) if length_match else 16

    no_symbols = "no symbol" in cmd or "without symbol" in cmd or "letters only" in cmd
    password = orch.password_gen.generate(length=length, use_symbols=not no_symbols)
    response = f"Generated password: {password}"
    orch.ctx.update(last_response=response, query=c)
    orch.speak(f"Here's your password: {password}")
    return True
