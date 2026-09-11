import re
import json
import logging
from typing import Dict, Any, List
from core.brain import Brain
from core.event_bus.bus import EventBus, Event

class SDDEngineer:
    """Autonomous engineering engine generating software specifications, patches, and automated tests."""
    def __init__(self, brain: Brain = None):
        self.brain = brain or Brain()
        self.bus = EventBus()
        self.logger = logging.getLogger("SDDEngineer")

    def parse_prd(self, prd_content: str) -> dict:
        """Parses a Product Requirement Document (PRD) into structured specifications."""
        self.logger.info("Parsing PRD requirements...")
        prompt = f"""
        Analyze the following Product Requirement Document (PRD) and compile a structured software specification.
        
        PRD Content:
        "{prd_content}"
        
        Return a JSON object containing:
        {{
            "title": "Project Title",
            "features": ["feature 1", "feature 2"],
            "classes": [
                {{
                    "name": "ClassName",
                    "methods": ["method1(args)", "method2()"],
                    "description": "purpose of class"
                }}
            ],
            "dependencies": ["package1", "package2"]
        }}
        
        Return ONLY valid JSON.
        """
        
        try:
            res_raw = self.brain.ask(prompt, system_override="You are a principal systems engineer. Return ONLY JSON.")
            cleaned = res_raw.strip()
            if cleaned.startswith("```"):
                match = re.search(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.DOTALL)
                if match: cleaned = match.group(1).strip()
            
            spec = json.loads(cleaned)
            self.bus.publish(Event("sdd.prd.parsed", {"title": spec.get("title")}))
            return spec
        except Exception as e:
            self.logger.error(f"PRD parsing failed: {e}")
            raise e

    def generate_task_graph(self, spec: dict) -> List[dict]:
        """Generates a structured topological coding implementation graph."""
        self.logger.info("Generating coding task graph...")
        prompt = f"""
        Based on this software specification, generate a sequential task list representing the implementation order:
        {json.dumps(spec)}
        
        Return a JSON array of task dicts:
        [
            {{
                "task_id": 1,
                "file_path": "relative/path/to/target.py",
                "purpose": "implement class X",
                "depends_on": []
            }}
        ]
        
        Return ONLY valid JSON.
        """
        try:
            res_raw = self.brain.ask(prompt, system_override="You are a task planner. Return ONLY JSON.")
            cleaned = res_raw.strip()
            if cleaned.startswith("```"):
                match = re.search(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.DOTALL)
                if match: cleaned = match.group(1).strip()
                
            task_graph = json.loads(cleaned)
            self.bus.publish(Event("sdd.graph.generated", {"tasks_count": len(task_graph)}))
            return task_graph
        except Exception as e:
            self.logger.error(f"Task graph generation failed: {e}")
            raise e

    def generate_patch(self, original_code: str, bug_description: str) -> str:
        """Formulates code changes or bug fixes as patch files/replacement codes."""
        self.logger.info(f"Generating patch for bug: {bug_description}")
        prompt = f"""
        Generate a bug fix or code patch for the following Python file:
        
        Bug Description: {bug_description}
        
        Original Code:
        ```python
        {original_code}
        ```
        
        Return ONLY the updated python code file. Do not write explanation, and do not wrap in markdown code blocks.
        """
        res = self.brain.ask(prompt)
        # Strip markdown wrappers if LLM still returned them
        res_clean = res.strip()
        if res_clean.startswith("```"):
            match = re.search(r"```(?:python)?\s*(.*?)\s*```", res_clean, re.DOTALL)
            if match: res_clean = match.group(1).strip()
            
        self.bus.publish(Event("sdd.patch.generated", {}))
        return res_clean
