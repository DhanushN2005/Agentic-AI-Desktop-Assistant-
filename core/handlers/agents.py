def handle_capability_delegation(orch, intent, c, silent):
    """Delegates to registered agents/capabilities; returns True if a capability handled the intent."""
    capability = orch.capability_registry.get_capability_for_intent(intent)
    if not capability:
        return False
    orch.logger.info(f"[REGISTRY] Routed '{intent}' to Capability '{capability}'")
    try:
        if capability == "browser":
            from adapters.browser_adapter import LegacyBrowserAdapter
            from agents.browser_agent import BrowserAgent
            res = BrowserAgent(LegacyBrowserAdapter(orch.browser)).execute_task({"action": intent, "target": c, "command": c})
            if res and "unavailable" not in str(res).lower():
                if not silent:
                    orch.speak(res)
                return True
        elif capability == "filesystem":
            from agents.coding_agent import CodingAgent
            res = CodingAgent(orch.dev).execute_task({"action": intent, "command": c})
            if res and "unavailable" not in str(res).lower():
                if not silent:
                    orch.speak(res)
                return True
        elif capability == "sdd":
            from sdd.engineer import SDDEngineer
            engineer = SDDEngineer(orch.brain)
            orch.speak("Initializing SDD Engineer. Analyzing requirements...")
            spec = engineer.parse_prd(c)
            dag_data = engineer.generate_task_graph(spec)
            orch.speak(f"Generated task graph with {len(dag_data)} components.")
            orch.ctx.update(last_sdd=spec)
            return True
    except Exception as cap_err:
        orch.logger.warning(f"[AGENT_DELEGATION] Fallback to legacy loop: {cap_err}")
    return False
