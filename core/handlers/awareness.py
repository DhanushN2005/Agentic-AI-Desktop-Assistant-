import re

from utils.config import Config


def handle_awareness(orch, c):
    """Handle self-awareness and status commands."""
    orch.send_to_ui("STATE", "PROCESSING")
    cmd = c.lower().strip()
    cmd = re.sub(r"^(flexi|flexie|hey flexie|ok flexie)\b", "", cmd).strip()

    # ---------------- "who am I" - USER identity ----------------
    if re.search(r"\bwho\s+am\s+i\b", cmd):
        user_name = getattr(Config, "USER_NAME", "you")
        facts = orch.awareness.recall_facts(limit=5)
        if facts:
            response = (f"If I remember right, you're {user_name}. "
                        "Things I've noted about you: " + "; ".join(facts))
        else:
            response = (f"You're {user_name} as far as I know. I haven't learned many "
                        "facts about you yet — tell me things to remember and I'll keep them.")

    # ---------------- "who are you" - Flexie identity ----------------
    elif any(w in cmd for w in ["who are you", "tell me about yourself", "what are you", "your name"]):
        response = orch.awareness.get_self_info()

    # ---------------- stats / status ----------------
    elif any(w in cmd for w in ["your stats", "your statistics", "how you doing", "system status"]):
        response = orch.awareness.get_stats()

    # ---------------- personality ----------------
    elif any(w in cmd for w in ["your personality", "what are you like", "describe yourself"]):
        response = orch.awareness.get_personality()

    # ---------------- learned knowledge ----------------
    elif any(w in cmd for w in ["what do you know", "what have you learned", "your knowledge"]):
        facts = orch.awareness.recall_facts(limit=5)
        response = "Things I know: " + "; ".join(facts) if facts else "I'm still learning about you."

    # ---------------- capabilities: "what can you do" ----------------
    elif any(w in cmd for w in ["what can you do", "what are you capable", "capabilities",
                                "abilities", "your skills", "your features", "what all can you do",
                                "how can you help", "your functions"]):
        response = orch.awareness.get_capabilities()

    # ---------------- limitations: "what can't you do" ----------------
    # Word-boundary matching ONLY — never a bare "what can" prefix (that used to
    # hijack questions like "what can I download..." via the substring "do").
    elif re.search(
        r"\bwhat\s+can(?:'?t|not)\s+you\b"                 # what can't/cannot you (do/handle/…)
        r"|\bcan(?:'?t|not)\s+you\s+do\b"                  # (why) can't you do …
        r"|\bwhat\s+are\s+your\s+(?:limitations?|limits?)\b"
        r"|\byour\s+limitations?\b"
        r"|\blimitations?\b",
        cmd,
    ):
        response = orch.awareness.get_limitations()

    # ---------------- sub-agents ----------------
    elif any(w in cmd for w in ["sub agent", "subagents", "sub-agent", "your agents",
                                "your team", "who works for you", "your helpers", "your workers",
                                "what agents"]):
        response = orch.awareness.get_sub_agents()

    # ---------------- modes ----------------
    elif any(w in cmd for w in ["your modes", "available modes", "what modes", "which modes",
                                "all modes", "mode list", "your mode"]):
        response = orch.awareness.get_modes()

    # ---------------- architecture / sub-systems ----------------
    elif any(w in cmd for w in ["how do you work", "how are you built", "your architecture",
                                "your systems", "system overview", "what are you made of",
                                "your components", "how do you function", "your setup",
                                "what systems"]):
        response = orch.awareness.get_system_map()

    # ---------------- fallback ----------------
    else:
        response = orch.awareness.get_self_info()

    orch.ctx.update(last_response=response, query=c)
    orch.speak(response)
    return True
