import re


def handle_memory_system(orch, c):
    """Handle memory-related commands."""
    orch.send_to_ui("STATE", "PROCESSING")
    cmd = c.lower().strip()
    cmd = re.sub(r"^(flexi|flexie|hey flexie|ok flexie)\b", "", cmd).strip()

    if any(w in cmd for w in ["remember that", "remember this", "keep in mind", "don't forget"]):
        fact = re.sub(r"^(remember that|remember this|keep in mind|don't forget)\s*", "", cmd).strip()
        if fact:
            orch.memory_system.set_preference(f"fact_{int(__import__('time').time())}", fact)
            orch.awareness.learn_fact(fact, "user_told")
            response = f"I'll remember that: {fact}"
        else:
            response = "What would you like me to remember?"
    elif any(w in cmd for w in ["what do you remember", "what have you learned", "recall"]):
        facts = orch.awareness.recall_facts(5)
        response = "I remember: " + "; ".join(facts) if facts else "I'm still learning about you."
    elif any(w in cmd for w in ["memory stats", "memory status", "how much do you remember"]):
        response = orch.memory_system.get_memory_stats()
    elif any(w in cmd for w in ["recent conversations", "what did we talk about", "conversation history"]):
        response = orch.memory_system.get_context_summary()
    elif "search memory" in cmd or "search for" in cmd:
        query = re.search(r"(?:search memory|search for)\s+(.+)", cmd)
        if query:
            results = orch.memory_system.search_memory(query.group(1).strip())
            response = "\n".join(results)
        else:
            response = "What should I search for in my memory?"
    elif any(w in cmd for w in ["popular topics", "what topics", "most discussed"]):
        topics = orch.memory_system.get_popular_topics(5)
        if topics:
            response = "Most discussed topics: " + ", ".join(f"{t['topic']} ({t['frequency']} times)" for t in topics)
        else:
            response = "No topics tracked yet."
    else:
        response = orch.memory_system.get_context_summary()

    orch.ctx.update(last_response=response, query=c)
    orch.speak(response)
    return True
