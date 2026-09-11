import os
import json
import logging
import uuid
import time
from typing import List, Dict, Any, Callable
from core.event_bus.bus import EventBus, Event

class DurableTask:
    """Represents a state-persistent, resumable execution task wrapping workflow steps."""
    def __init__(self, steps: List[str], task_id: str = None):
        self.task_id = task_id or str(uuid.uuid4())
        self.steps = steps
        self.current_step_idx = 0
        self.status = "pending"  # pending, running, completed, failed
        self.checkpoints: Dict[int, Dict[str, Any]] = {}
        self.created_at = time.time()
        self.updated_at = time.time()

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "steps": self.steps,
            "current_step_idx": self.current_step_idx,
            "status": self.status,
            "checkpoints": self.checkpoints,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }

    @classmethod
    def from_dict(cls, data: dict):
        task = cls(data["steps"], data["task_id"])
        task.current_step_idx = data["current_step_idx"]
        task.status = data["status"]
        # Convert string keys back to int for checkpoints
        task.checkpoints = {int(k): v for k, v in data.get("checkpoints", {}).items()}
        task.created_at = data.get("created_at", time.time())
        task.updated_at = data.get("updated_at", time.time())
        return task

class DurableWorkflowRuntime:
    """Durable workflow runtime executing resumable task pipelines and state checkpoints."""
    def __init__(self, storage_path: str = "flexie_durable_workflows.json"):
        self.storage_path = storage_path
        self.bus = EventBus()
        self.logger = logging.getLogger("DurableRuntime")
        self.active_tasks: Dict[str, DurableTask] = {}
        self._load_state()

    def _load_state(self):
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, "r") as f:
                    data = json.load(f)
                    for t_id, t_dict in data.items():
                        self.active_tasks[t_id] = DurableTask.from_dict(t_dict)
            except Exception as e:
                self.logger.error(f"Failed to load durable workflow state: {e}")

    def save_state(self):
        try:
            with open(self.storage_path, "w") as f:
                json.dump({t_id: t.to_dict() for t_id, t in self.active_tasks.items()}, f, indent=4)
        except Exception as e:
            self.logger.error(f"Failed to save durable workflow state: {e}")

    def create_task(self, steps: List[str]) -> DurableTask:
        task = DurableTask(steps)
        self.active_tasks[task.task_id] = task
        self.save_state()
        self.bus.publish(Event("workflow.created", {"task_id": task.task_id, "steps_count": len(steps)}))
        return task

    def record_checkpoint(self, task_id: str, step_idx: int, state_data: Dict[str, Any]):
        """Saves intermediate execution progress for resume triggers."""
        task = self.active_tasks.get(task_id)
        if task:
            task.checkpoints[step_idx] = {
                "timestamp": time.time(),
                "state": state_data
            }
            task.updated_at = time.time()
            self.save_state()
            self.bus.publish(Event("workflow.checkpoint", {"task_id": task_id, "step_idx": step_idx}))

    def execute(self, task_id: str, execute_step_fn: Callable[[str], bool]) -> bool:
        """Executes workflow steps sequentially with durable checkpoint logs."""
        task = self.active_tasks.get(task_id)
        if not task:
            return False

        task.status = "running"
        self.save_state()
        self.bus.publish(Event("workflow.start", {"task_id": task_id, "resume_idx": task.current_step_idx}))

        success = True
        while task.current_step_idx < len(task.steps):
            step = task.steps[task.current_step_idx]
            self.logger.info(f"Durable Runtime: Running task {task_id} step {task.current_step_idx}: '{step}'")
            
            # Execute step through runner callback
            try:
                step_success = execute_step_fn(step)
            except Exception as e:
                self.logger.error(f"Step execution exception: {e}")
                step_success = False

            if step_success:
                self.record_checkpoint(task_id, task.current_step_idx, {"status": "success", "step": step})
                task.current_step_idx += 1
                self.save_state()
            else:
                self.logger.warning(f"Durable Runtime: Step execution failed at index {task.current_step_idx}")
                task.status = "failed"
                self.save_state()
                self.bus.publish(Event("workflow.failed", {"task_id": task_id, "failed_idx": task.current_step_idx}, priority=0))
                success = False
                break

        if success:
            task.status = "completed"
            self.save_state()
            self.bus.publish(Event("workflow.completed", {"task_id": task_id}))

        return success

    def resume_task(self, task_id: str, execute_step_fn: Callable[[str], bool]) -> bool:
        """Resumes a failed or interrupted task from its last uncompleted checkpoint."""
        task = self.active_tasks.get(task_id)
        if not task or task.status == "completed":
            return False

        self.logger.info(f"Durable Runtime: Resuming task {task_id} from step index {task.current_step_idx}")
        return self.execute(task_id, execute_step_fn)
