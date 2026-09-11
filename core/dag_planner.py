import concurrent.futures
import logging
from typing import List, Callable

# FIX 10: Import ActionResult for structured task results.
# Imported here so DAGPlanner can surface failures to execute_graph.
try:
    from core.action_result import ActionResult
except ImportError:
    ActionResult = None  # Graceful degradation if module not yet present


class DAGTask:
    def __init__(self, task_id: str, command: str, dependencies: List[str] = None):
        self.task_id = task_id
        self.command = command
        self.dependencies = dependencies or []
        self.status = "PENDING"


class DAGPlanner:
    """
    Executes a Directed Acyclic Graph of tasks using a thread pool.

    IMPORTANT — executor_callback contract (FIX 3, FIX 8):
        The callback passed to __init__ MUST be a BLOCKING function that
        does not return until the command has actually been executed.
        Use orchestrator._blocking_execute, NOT handle_command directly.

        handle_command contains a thread-safety guard that immediately queues
        the command and returns — this makes DAG nodes appear complete before
        the command has run. _blocking_execute uses threading.Event to wait
        for true completion (no busy-waiting).
    """

    def __init__(self, executor_callback: Callable[[str], object]):
        self.logger = logging.getLogger("Flexie.DAGPlanner")
        # executor_callback must be a blocking call — see docstring above.
        self.executor_callback = executor_callback

    def execute_graph(self, tasks: List[DAGTask]):
        self.logger.info(f"[DAG] Starting DAG execution with {len(tasks)} tasks.")

        task_dict = {t.task_id: t for t in tasks}
        completed = set()
        failed = set()

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = {}

            while len(completed) + len(failed) < len(tasks):
                # Find ready tasks
                for task_id, task in task_dict.items():
                    if task.status == "PENDING":
                        # Check dependencies
                        if all(dep in completed for dep in task.dependencies):
                            if any(dep in failed for dep in task.dependencies):
                                task.status = "CANCELLED"
                                failed.add(task_id)
                                self.logger.warning(f"[DAG] Task {task_id} cancelled due to failed dependency.")
                            else:
                                task.status = "RUNNING"
                                self.logger.info(f"[DAG] Scheduling {task_id}: {task.command}")
                                futures[executor.submit(self._run_task, task)] = task_id

                # Wait for at least one to finish
                if futures:
                    done, _ = concurrent.futures.wait(futures.keys(), return_when=concurrent.futures.FIRST_COMPLETED)
                    for future in done:
                        task_id = futures.pop(future)
                        try:
                            result = future.result()
                            # FIX 3: Check ActionResult.success — only mark complete
                            # when the action actually succeeded (not just "queued").
                            if ActionResult is not None and result is not None and not result.success:
                                raise RuntimeError(f"Action failed: {result.message}")
                            completed.add(task_id)
                            task_dict[task_id].status = "COMPLETED"
                            self.logger.info(f"[DAG] Completed {task_id}")
                        except Exception as e:
                            failed.add(task_id)
                            task_dict[task_id].status = "FAILED"
                            self.logger.error(f"[DAG] Failed {task_id}: {e}")
                else:
                    # Deadlock or all done
                    break

        self.logger.info(f"[DAG] Execution finished. Completed: {len(completed)}, Failed: {len(failed)}")

    def _run_task(self, task: DAGTask):
        """
        Execute a single DAG task.

        FIX 3, FIX 8: executor_callback must be _blocking_execute (not handle_command).
        _blocking_execute uses threading.Event to wait for completion — no busy waiting.
        Returns an ActionResult (or None if callback does not return one).
        """
        self.logger.info(f"[DAG] Running task {task.task_id}: {task.command}")
        result = self.executor_callback(task.command)
        return result  # ActionResult or None

