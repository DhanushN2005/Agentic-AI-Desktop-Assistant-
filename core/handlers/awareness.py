import re


def handle_awareness(orch, c):
    """Handle self-awareness and status commands."""
    orch.send_to_ui("STATE", "PROCESSING")
    cmd = c.lower().strip()
    cmd = re.sub(r"^(flexi|flexie|hey flexie|ok flexie)\b", "", cmd).strip()

    if any(w in cmd for w in ["who are you", "tell me about yourself", "what are you", "your name"]):
        response = orch.awareness.get_self_info()
    elif any(w in cmd for w in ["your stats", "your statistics", "how you doing", "system status"]):
        response = orch.awareness.get_stats()
    elif any(w in cmd for w in ["your personality", "what are you like", "describe yourself"]):
        response = orch.awareness.get_personality()
    elif any(w in cmd for w in ["what do you know", "what have you learned", "your knowledge"]):
        facts = orch.awareness.recall_facts(5)
        response = "Things I know: " + "; ".join(facts) if facts else "I'm still learning about you."
    else:
        response = orch.awareness.get_self_info()

    orch.ctx.update(last_response=response, query=c)
    orch.speak(response)
    return True
