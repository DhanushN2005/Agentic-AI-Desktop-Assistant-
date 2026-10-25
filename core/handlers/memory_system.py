import os
import re
import time


def handle_memory_system(orch, c):
    """Unified natural-language memory interface (Ari & Monaw style)."""
    orch.send_to_ui("STATE", "PROCESSING")
    cmd = c.lower().strip()
    cmd = re.sub(r"^(flexi|flexie|hey flexie|ok flexie)\b", "", cmd).strip()

    mm = getattr(orch, "memory_manager", None)

    # 1. Forget / delete commands
    if any(cmd.startswith(p) for p in ["forget that ", "forget ", "remove memory ", "delete memory "]):
        target = re.sub(r"^(forget that|forget|remove memory|delete memory)\s*", "", cmd).strip()
        if not target:
            response = "What would you like me to forget?"
        else:
            forgotten = False
            if mm:
                # Direct match or substring search
                if mm.forget(target):
                    forgotten = True
                else:
                    matches = mm.search(target, limit=3)
                    for m in matches:
                        mm.forget(m.key)
                        forgotten = True
            if hasattr(orch, "memory") and hasattr(orch.memory, "forget"):
                try:
                    orch.memory.forget(target)
                    forgotten = True
                except Exception:
                    pass
            response = f"I have forgotten: {target}." if forgotten else f"I couldn't find any memory matching '{target}'."

    # 2. Explicit Remember commands
    elif any(w in cmd for w in ["remember that", "remember this", "keep in mind", "don't forget", "remember"]):
        raw_cmd = re.sub(r"^(flexi|flexie|hey flexie|ok flexie)\b", "", c, flags=re.IGNORECASE).strip()
        fact = re.sub(r"^(remember that|remember this|keep in mind|don't forget|remember)\s*", "", raw_cmd, flags=re.IGNORECASE).strip()
        if fact:
            # Determine category: preferences vs facts
            is_pref = any(p in fact.lower() for p in ["i like", "i prefer", "my favorite", "my preferred", "i love"])
            
            # Key/value extraction if phrased as "X is Y" or "X are Y"
            fact_lower = fact.lower()
            if " is " in fact_lower or " are " in fact_lower:
                sep = " is " if " is " in fact_lower else " are "
                idx = fact_lower.index(sep)
                store_key = fact[:idx].strip()
                store_val = fact[idx + len(sep):].strip()
            else:
                store_key = fact[:50].strip()
                store_val = fact.strip()

            cat = None
            if mm:
                from core.memory_manager import MemoryCategory
                cat = MemoryCategory.PREFERENCES if is_pref else MemoryCategory.FACTS
                mm.remember(store_key, store_val, category=cat, importance=0.85, tags=["user_explicit"])

            if hasattr(orch, "memory_system") and orch.memory_system:
                orch.memory_system.set_preference(f"fact_{int(time.time())}", fact)
            if hasattr(orch, "awareness") and orch.awareness:
                orch.awareness.learn_fact(fact, "user_told")
            if hasattr(orch, "memory") and hasattr(orch.memory, "store"):
                orch.memory.store(store_key, store_val, cat="user")

            response = f"Got it. I'll remember that: {fact}"
        else:
            response = "What would you like me to remember?"

    # 3. View / Open memory wiki
    elif any(w in cmd for w in ["show memory", "open memory", "memory wiki", "view memory"]):
        if mm:
            wiki_content = mm.export_to_markdown()
            data_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data")
            wiki_path = os.path.abspath(os.path.join(data_dir, "MEMORY.md"))
            orch.send_to_ui("SAY", f"### 🧠 Memory Wiki\n\n```markdown\n{wiki_content}\n```")
            response = f"Your memory wiki is saved at {wiki_path} and displayed on your screen."
        else:
            response = "Memory wiki is not currently available."

    # 4. Recall / what do you remember / list memory
    elif any(w in cmd for w in ["what do you remember", "what have you learned", "what do you know", "list memory", "recall"]):
        facts = []
        if mm:
            from core.memory_manager import MemoryCategory
            prefs = mm.get_by_category(MemoryCategory.PREFERENCES)
            learned = mm.get_by_category(MemoryCategory.FACTS)
            all_entries = prefs + learned
            if all_entries:
                facts = [f"{e.key}: {e.value}" for e in all_entries[:7]]

        if not facts and hasattr(orch, "awareness") and orch.awareness:
            facts = orch.awareness.recall_facts(limit=5)

        if not facts and hasattr(orch, "memory") and hasattr(orch.memory, "all_facts"):
            raw_facts = orch.memory.all_facts()
            facts = [f"{k}: {v}" for k, v, _ in raw_facts[:5]]

        response = "Here is what I remember about you:\n" + "\n".join(f"• {f}" for f in facts) if facts else "My memory is currently empty. Tell me something to remember!"

    elif any(w in cmd for w in ["memory stats", "memory status", "how much do you remember"]):
        if mm:
            response = mm.to_summary()
        elif hasattr(orch, "memory_system") and orch.memory_system:
            response = orch.memory_system.get_memory_stats()
        else:
            response = "Memory system active."

    elif any(w in cmd for w in ["recent conversations", "what did we talk about", "conversation history"]):
        if hasattr(orch, "memory_system") and orch.memory_system:
            response = orch.memory_system.get_context_summary()
        else:
            response = "No recent conversation history available."

    elif "search memory" in cmd or "search for" in cmd:
        query = re.search(r"(?:search memory|search for)\s+(.+)", cmd)
        if query:
            q_text = query.group(1).strip()
            results = []
            if mm:
                entries = mm.search(q_text, limit=5)
                results = [f"• {e.key}: {e.value}" for e in entries]
            elif hasattr(orch, "memory_system") and orch.memory_system:
                results = orch.memory_system.search_memory(q_text)
            response = "\n".join(results) if results else f"No memories found matching '{q_text}'."
        else:
            response = "What should I search for in my memory?"

    elif any(w in cmd for w in ["popular topics", "what topics", "most discussed"]):
        if hasattr(orch, "memory_system") and orch.memory_system:
            topics = orch.memory_system.get_popular_topics(5)
            if topics:
                response = "Most discussed topics: " + ", ".join(f"{t['topic']} ({t['frequency']} times)" for t in topics)
            else:
                response = "No topics tracked yet."
        else:
            response = "No topics tracked yet."
    else:
        if mm:
            response = mm.to_summary()
        elif hasattr(orch, "memory_system") and orch.memory_system:
            response = orch.memory_system.get_context_summary()
        else:
            response = "Memory system is online."

    orch.ctx.update(last_response=response, query=c)
    orch.speak(response)
    return True
