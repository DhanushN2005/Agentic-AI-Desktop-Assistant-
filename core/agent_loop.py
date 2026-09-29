"""ReAct Agent Loop — LangGraph-based agentic planning and tool execution.

The agent reasons (LLM) → acts (tool) → observes → reflects → repeats
until the task is complete or max steps reached.

Uses a local Ollama deepseek-r1 model for reasoning by default.
"""
import logging
import json
from typing import TypedDict, List, Optional, Callable
from urllib.request import urlopen, Request
from functools import wraps

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

logger = logging.getLogger("AgentLoop")


class AgentState(TypedDict):
    messages: List[dict]
    tools: List[dict]
    step: int
    max_steps: int
    result: Optional[str]
    tool_outputs: List[dict]
    reasoning: Optional[str]


def _ollama_available() -> bool:
    try:
        req = Request("http://localhost:11434/api/tags")
        with urlopen(req, timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def _ollama_chat(model: str, messages: list, temperature: float = 0.3) -> str:
    payload = {"model": model, "messages": messages, "stream": False,
               "options": {"temperature": temperature, "num_predict": 2048}}
    try:
        req = Request("http://localhost:11434/api/chat", data=json.dumps(payload).encode(),
                       headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=90) as resp:
            obj = json.loads(resp.read().decode())
            return obj.get("message", {}).get("content", "")
    except Exception as e:
        logger.debug(f"[AgentLoop] Ollama call failed: {e}")
        return ""


def _execute_tool(tool_name: str, tool_args: dict, registry=None) -> str:
    """Execute a registered tool by name. Returns string result."""
    if registry and hasattr(registry, 'get_tool'):
        try:
            tool = registry.get_tool(tool_name)
            if tool and hasattr(tool, 'execute'):
                return tool.execute(**tool_args)
        except Exception as e:
            return f"Tool '{tool_name}' error: {e}"
    return f"Tool '{tool_name}' not available in registry."


def _create_tool_node(tool_registry):
    """Factory for the tool execution node."""
    def tool_node(state: AgentState) -> dict:
        tool_calls = []
        for msg in reversed(state["messages"]):
            if msg.get("role") == "assistant" and "tool_calls" in str(msg):
                try:
                    tc = json.loads(msg["tool_calls"]) if isinstance(msg["tool_calls"], str) else msg["tool_calls"]
                    for call in tc:
                        tool_calls.append(call)
                except (json.JSONDecodeError, TypeError):
                    pass
        outputs = []
        for tc in tool_calls:
            name = tc.get("name", tc.get("function", {}).get("name", ""))
            args = tc.get("arguments", tc.get("function", {}).get("arguments", {}))
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    pass
            result = _execute_tool(name, args if isinstance(args, dict) else {}, tool_registry)
            outputs.append({"name": name, "result": result})
            state["messages"].append({"role": "tool", "content": result, "tool_call_id": tc.get("id")})
            state["tool_outputs"].append({"name": name, "result": result})
        return {"messages": state["messages"], "tool_outputs": outputs, "step": state["step"] + 1}
    return tool_node


def _create_llm_node(system_prompt: str):
    """Factory for the LLM reasoning node."""
    def llm_node(state: AgentState) -> dict:
        messages = [{"role": "system", "content": system_prompt}] + list(state["messages"])
        response = _ollama_chat("deepseek-r1", messages)
        new_messages = list(state["messages"]) + [{"role": "assistant", "content": response}]
        return {"messages": new_messages, "reasoning": response, "step": state["step"] + 1}
    return llm_node


def _create_router_node(tool_registry):
    """Factory for the router: decide if more tool calls needed or if done."""
    def router_node(state: AgentState) -> dict:
        last_msg = state["messages"][-1] if state["messages"] else {}
        content = last_msg.get("content", "")
        has_tool_calls = '"tool_calls"' in content or '"function"' in content
        if has_tool_calls and state["step"] < state["max_steps"]:
            return {"next": "tool_node"}
        return {"next": "end"}
    return router_node


class ReActAgent:
    """ReAct agent loop: Reason → Act → Observe → Reflect → Repeat."""

    def __init__(self, system_prompt: str = None, tool_registry=None, max_steps: int = 5):
        self.system_prompt = system_prompt or ("You are an autonomous agent. Reason step by step, "
                                               "call tools when needed, and produce the final answer.")
        self.tool_registry = tool_registry
        self.max_steps = max_steps
        self.graph = None
        self._build_graph()

    def _build_graph(self):
        """Build the LangGraph ReAct graph."""
        if not _ollama_available():
            logger.warning("Ollama not available — ReActAgent created but will not execute.")
            return

        workflow = StateGraph(AgentState)

        llm_node = _create_llm_node(self.system_prompt)
        tool_node_fn = _create_tool_node(self.tool_registry)
        router_fn = _create_router_node(self.tool_registry)

        workflow.add_node("llm_node", llm_node)
        workflow.add_node("tool_node", tool_node_fn)
        workflow.add_node("router_node", router_fn)

        workflow.set_entry_point("llm_node")
        workflow.add_edge("llm_node", "router_node")
        workflow.add_conditional_edges(
            "router_node",
            lambda state: state["next"],
            {"tool_node": "tool_node", "end": END},
        )
        workflow.add_edge("tool_node", "llm_node")

        memory = MemorySaver()
        self.graph = workflow.compile(checkpointer=memory)

    def run(self, prompt: str) -> str:
        """Run the agent on a prompt. Returns the final result string."""
        if self.graph is None:
            return "ReAct agent is not available (Ollama not running). Use direct LLM mode."
        initial_state = AgentState(
            messages=[{"role": "user", "content": prompt}],
            tools=[],
            step=0,
            max_steps=self.max_steps,
            result=None,
            tool_outputs=[],
            reasoning=None,
        )
        try:
            for event in self.graph.stream(initial_state, config={"configurable": {"thread_id": "flexie"}}):
                pass
            final_messages = event.get("messages", []) if isinstance(event, dict) else []
            for msg in reversed(final_messages):
                if msg.get("role") == "assistant" and "tool_calls" not in str(msg):
                    return msg.get("content", "")
            return final_messages[-1].get("content", "") if final_messages else "Agent completed."
        except Exception as e:
            logger.error(f"[ReActAgent] Run error: {e}")
            return f"Agent error: {e}"


def make_agent(prompt: str, tool_registry=None, max_steps: int = 5) -> str:
    """Convenience: create and run a ReAct agent, return final answer."""
    agent = ReActAgent(tool_registry=tool_registry, max_steps=max_steps)
    return agent.run(prompt)
