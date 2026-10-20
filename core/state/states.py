from enum import Enum


class TaskState(Enum):
    """Estados possíveis de uma tarefa no Atom."""

    CREATED = "created"
    PLANNING = "planning"
    READY = "ready"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
