import threading
import time
import logging

class AgentArbitrator:
    """
    Manages locks and execution rights across different agentic modules.
    Ensures that only one specialized agent (e.g., RecoveryAgent or VerificationAgent)
    can control a specific task or resource at a given time.
    """
    def __init__(self):
        self.logger = logging.getLogger("Flexie.Arbitrator")
        self._locks = {}
        self._lock_mutex = threading.Lock()
        
    def acquire_lock(self, resource_id: str, agent_id: str, timeout: float = 5.0) -> bool:
        """
        Attempts to acquire a lock for a specific resource.
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            with self._lock_mutex:
                if resource_id not in self._locks:
                    self._locks[resource_id] = agent_id
                    self.logger.debug(f"[ARBITRATOR] Lock acquired on '{resource_id}' by '{agent_id}'")
                    return True
                elif self._locks[resource_id] == agent_id:
                    # Already owns the lock
                    return True
            time.sleep(0.1)
            
        self.logger.warning(f"[ARBITRATOR] '{agent_id}' failed to acquire lock on '{resource_id}'. Currently held by '{self._locks.get(resource_id)}'")
        return False
        
    def release_lock(self, resource_id: str, agent_id: str):
        """
        Releases a lock if the requesting agent currently owns it.
        """
        with self._lock_mutex:
            if self._locks.get(resource_id) == agent_id:
                del self._locks[resource_id]
                self.logger.debug(f"[ARBITRATOR] Lock released on '{resource_id}' by '{agent_id}'")
            else:
                self.logger.warning(f"[ARBITRATOR] '{agent_id}' attempted to release lock on '{resource_id}' but does not own it.")
                
    def force_release(self, resource_id: str):
        """
        Admin override to force release a lock.
        """
        with self._lock_mutex:
            if resource_id in self._locks:
                owner = self._locks.pop(resource_id)
                self.logger.warning(f"[ARBITRATOR] Force released lock on '{resource_id}' (was held by '{owner}')")
