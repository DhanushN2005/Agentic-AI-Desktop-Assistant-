import re

from utils.voice_parse import parse_number, strip_wake

_UUID_RE = re.compile(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", re.IGNORECASE)
_VERSION_RE = re.compile(r"\b(?:uuid\s*|guid\s*|version\s+|v)([1-5])\b", re.IGNORECASE)
_COUNT_RES = [
    re.compile(r"\b(\d+)\s*(?:uuids?|guids?|ids?|identifiers?)\b", re.IGNORECASE),
    re.compile(r"\b(?:generate|create|make|give\s+me|get)\s+(\d+)\b", re.IGNORECASE),
    re.compile(r"\b(?:batch|bunch|list)\s+of\s+(\d+)\b", re.IGNORECASE),
]
_WORD_COUNT_RE = re.compile(
    r"\b(?:generate|create|make|give\s+me|get)\s+((?:a\s+couple|an?|one|two|three|four|five|six|seven|eight|nine|ten|twenty|thirty|fifty)(?:\s+of)?)\s+(?:uuids?|guids?)\b",
    re.IGNORECASE,
)


def _parse_count(cmd: str):
    """Number of UUIDs requested: None = unspecified.  'v4'/'v1' are versions,
    never counts."""
    cleaned = _VERSION_RE.sub(" ", cmd)
    for rx in _COUNT_RES:
        m = rx.search(cleaned)
        if m:
            return int(m.group(1))
    m = _WORD_COUNT_RE.search(cleaned)
    if m:
        n = parse_number(m.group(1))
        if n:
            return int(n)
    return None


def handle_uuid(orch, c):
    """Handle UUID generation commands."""
    orch.send_to_ui("STATE", "PROCESSING")
    original = strip_wake(c)
    cmd = original.lower()
    uuid_match = _UUID_RE.search(original)

    if "valid" in cmd or "check" in cmd:
        response = orch.uuid_gen.is_valid(uuid_match.group(1)) if uuid_match else "Provide a UUID to check."
    elif "timestamp" in cmd:
        response = orch.uuid_gen.timestamp(uuid_match.group(1)) if uuid_match else "Provide a UUID v1 to get timestamp."
    else:
        vm = _VERSION_RE.search(cmd)
        version = int(vm.group(1)) if vm else 4
        count = _parse_count(cmd)
        wants_many = any(w in cmd for w in ("batch", "multiple", "several", "bunch", "list"))
        if count is None and wants_many:
            count = 5
        if count is not None and count < 1:
            response = "How many UUIDs? Choose a number from 1 to 100."
        elif count is not None and count > 1:
            response = orch.uuid_gen.generate_batch(count)
            if count > 100:
                response = "I can generate at most 100 at a time, so here are 100.\n" + response
        elif version == 1:
            response = orch.uuid_gen.generate_v1()
        elif version == 5:
            ns_match = re.search(r"namespace\s+(\S+)", original, re.IGNORECASE)
            name_match = re.search(r"\bname\s+(\S+)", original, re.IGNORECASE)
            ns = ns_match.group(1) if ns_match else "example.com"
            name = name_match.group(1) if name_match else "test"
            response = orch.uuid_gen.generate_namespace(ns, name)
        else:
            response = orch.uuid_gen.generate_v4()

    orch.ctx.update(last_response=response, query=c)
    orch.speak(response)
    return True
