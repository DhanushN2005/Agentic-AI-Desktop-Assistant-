import time
import logging

class ReflectionReport:
    def __init__(self, step_name: str, success: bool, latency: float, retries: int):
        self.step_name = step_name
        self.success = success
        self.latency = latency
        self.retries = retries
        self.quality_score = self._calculate_score()
        
    def _calculate_score(self) -> float:
        score = 100.0
        if not self.success:
            return 0.0
        # Deduct points for retries
        score -= (self.retries * 20.0)
        # Deduct points for latency > 5s
        if self.latency > 5.0:
            score -= min(30.0, (self.latency - 5.0) * 2)
        return max(0.0, score)
        
    def __str__(self):
        return f"ReflectionReport(step='{self.step_name}', success={self.success}, latency={self.latency:.2f}s, retries={self.retries}, score={self.quality_score:.1f}/100)"

class TaskCritic:
    """
    Evaluates execution quality post-execution.
    Scores tasks based on success, latency, and retries.
    """
    def __init__(self):
        self.logger = logging.getLogger("Flexie.Reflection")
        self.history = []

    def critique(self, step_name: str, start_time: float, end_time: float, success: bool, retries: int) -> ReflectionReport:
        latency = end_time - start_time
        report = ReflectionReport(step_name, success, latency, retries)
        self.history.append(report)
        
        self.logger.info(f"[REFLECTION] {report}")
        
        if report.quality_score < 50.0:
            self.logger.warning(f"[REFLECTION] Low execution quality for '{step_name}'. Needs improvement.")
            
        return report
