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


class StepNodeState(Enum):
    """Estados possíveis de um StepNode no grafo de execução."""

    CREATED = "created"
    CLASSIFIED = "classified"
    DECOMPOSING = "decomposing"
    READY = "ready"
    RUNNING = "running"
    RECOMPOSING = "recomposing"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"
