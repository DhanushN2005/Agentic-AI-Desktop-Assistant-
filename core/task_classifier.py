from enum import Enum, auto

class TaskType(Enum):
    GOAL = auto()
    ACTION = auto()
    SUBACTION = auto()

class TaskState(Enum):
    PENDING = auto()
    RUNNING = auto()
    COMPLETED = auto()
    FAILED = auto()

class TaskClassifier:
    """
    Classifies tasks into GOAL, ACTION, or SUBACTION to enforce
    strict boundaries on what is allowed to enter the semantic planner.
    """
    def __init__(self, atomic_actions_set):
        self.atomic_actions = atomic_actions_set
        
    def classify(self, intent: str, is_subcommand: bool) -> TaskType:
        """
        Classify intent based on subcommand status and atomic registries.
        Rules:
        - If it is in ATOMIC_ACTIONS, it is an ACTION (if top-level) or SUBACTION (if nested).
        - If it is NOT atomic, and NOT a subcommand, it is a GOAL.
        - If it is NOT atomic, and IS a subcommand, it defaults to a SUBACTION to block re-planning.
        """
        if intent in self.atomic_actions:
            return TaskType.SUBACTION if is_subcommand else TaskType.ACTION
        else:
            return TaskType.SUBACTION if is_subcommand else TaskType.GOAL
