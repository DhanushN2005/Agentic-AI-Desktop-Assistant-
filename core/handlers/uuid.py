import re


def handle_uuid(orch, c):
    """Handle UUID generation commands."""
    orch.send_to_ui("STATE", "PROCESSING")
    cmd = c.lower().strip()
    cmd = re.sub(r"^(flexi|flexie|hey flexie|ok flexie)\b", "", cmd).strip()

    if "batch" in cmd or "multiple" in cmd or "generate" in cmd:
        count_match = re.search(r"(\d+)", cmd)
        count = int(count_match.group(1)) if count_match else 5
        response = orch.uuid_gen.generate_batch(count)
    elif "v1" in cmd:
        response = orch.uuid_gen.generate_v1()
    elif "v5" in cmd:
        ns_match = re.search(r"namespace\s+(\S+)", cmd)
        name_match = re.search(r"name\s+(\S+)", cmd)
        ns = ns_match.group(1) if ns_match else "example.com"
        name = name_match.group(1) if name_match else "test"
        response = orch.uuid_gen.generate_namespace(ns, name)
    elif "valid" in cmd or "check" in cmd:
        uuid_match = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", cmd, re.IGNORECASE)
        if uuid_match:
            response = orch.uuid_gen.is_valid(uuid_match.group(1))
        else:
            response = "Provide a UUID to check."
    elif "timestamp" in cmd:
        uuid_match = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", cmd, re.IGNORECASE)
        if uuid_match:
            response = orch.uuid_gen.timestamp(uuid_match.group(1))
        else:
            response = "Provide a UUID v1 to get timestamp."
    else:
        response = orch.uuid_gen.generate_v4()

    orch.ctx.update(last_response=response, query=c)
    orch.speak(response)
    return True
