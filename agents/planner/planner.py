import re
import json
import logging
from typing import List, Dict, Any
from agents.base import BaseAgent
from core.brain import Brain

class PlannerAgent(BaseAgent):
    """Decomposes complex goals into sequential task graphs (DAGs) and formats step lists."""
    def __init__(self, brain_instance: Brain = None):
        super().__init__("planner", "Task Decomposition & Graph Scheduler")
        self.brain = brain_instance or Brain()

    def execute_task(self, payload: Dict[str, Any]) -> dict:
        goal = payload.get("goal")
        if not goal:
            raise ValueError("Payload missing 'goal' parameter.")

        self.logger.info(f"Decomposing goal: '{goal}'")
        
        # Build prompt to generate structured DAG
        prompt = f"""
        Analyze the following high-level user goal for a desktop assistant named Flexie:
        User Goal: "{goal}"
        
        Decompose this goal into a directed workflow graph (DAG) representing sequential execution steps.
        
        Return a JSON object matching this structure EXACTLY:
        {{
            "goal": "string",
            "steps": [
                {{
                    "id": 1,
                    "desc": "concise description of step",
                    "action": "standard assistant command (e.g. 'search for ...', 'create a folder called ...', 'open notepad', 'paste response')",
                    "depends_on": []
                }}
            ]
        }}
        
        Do not add any Markdown blocks or formatting outside the JSON. Return only the raw JSON string.
        """
        
        try:
            res_raw = self.brain.ask(prompt, system_override="You are a system architect. Return ONLY valid JSON.")
            
            # Simple JSON extraction
            json_str = res_raw.strip()
            if json_str.startswith("```"):
                match = re.search(r"```(?:json)?\s*(.*?)\s*```", json_str, re.DOTALL)
                if match:
                    json_str = match.group(1).strip()
            
            plan_data = json.loads(json_str)
            steps = plan_data.get("steps", [])
            
            # Formulate sequential list based on dependencies (Topological sort simulation)
            sorted_steps = self._topological_sort(steps)
            
            self.logger.info(f"Goal successfully planned. Sorted steps count: {len(sorted_steps)}")
            return {
                "goal": goal,
                "dag": plan_data,
                "sorted_steps": sorted_steps
            }
        except Exception as e:
            self.logger.error(f"Failed to decompose goal: {e}")
            raise e

    def _topological_sort(self, steps: List[Dict[str, Any]]) -> List[str]:
        """Performs a dependency resolution sorting to return sequential string commands."""
        # Standard Kahn's algorithm or simple iteration for small DAG lists
        sorted_cmds = []
        visited = set()
        
        # Build index mapping ID -> Step
        steps_map = {step["id"]: step for step in steps}
        
        def visit(step_id):
            if step_id in visited:
                return
            step = steps_map.get(step_id)
            if not step:
                return
            
            # Visit dependencies first
            for dep in step.get("depends_on", []):
                visit(dep)
                
            visited.add(step_id)
            sorted_cmds.append(step["action"])

        for step in steps:
            visit(step["id"])
            
        return sorted_cmds
