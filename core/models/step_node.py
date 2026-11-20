from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from core.state.states import StepNodeState


def normalize_node_id(node_id: int | str) -> str:
    """Normaliza identificadores de StepNode para representação em string."""
    if isinstance(node_id, bool):
        raise ValueError("Identificador de StepNode não pode ser booleano.")
    value = str(node_id).strip()
    if not value:
        raise ValueError("Identificador de StepNode não pode ser vazio.")
    return value


@dataclass
class StepNode:
    """
    Unidade principal de planejamento, classificação e execução do ATOM.

    Mantém três dimensões independentes:
    - plan: dados e contratos gerados pelo planejamento;
    - classification: operação e metadados identificados pelo classificador;
    - state: estado atual do ciclo de vida do nó.
    """

    id: str
    plan: dict[str, Any]
    classification: dict[str, Any] | None = None
    state: StepNodeState = StepNodeState.CREATED

    local_id: int | str | None = None
    parent_id: str | None = None
    children_ids: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    depth: int = 0

    role: str | None = None
    decomposition_decision: dict[str, Any] | None = None
    recomposition_contract: dict[str, Any] | None = None

    result: str | None = None
    verification: dict[str, Any] | None = None
    error: str | None = None
    attempts: int = 0
    updated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def is_leaf(self) -> bool:
        """Indica se o nó não possui filhos e pode ser executado diretamente."""
        return len(self.children_ids) == 0

    @property
    def description(self) -> str:
        return str(self.plan.get("description", ""))

    @property
    def objective(self) -> str:
        return str(self.plan.get("objective", ""))

    @property
    def contracts(self) -> dict[str, list[str]]:
        raw = self.plan.get("contracts")
        if isinstance(raw, dict):
            return raw
        return {"preconditions": [], "postconditions": [], "invariants": []}

    @property
    def effects(self) -> dict[str, list[str]]:
        raw = self.plan.get("effects")
        if isinstance(raw, dict):
            return raw
        return {"reads": [], "creates": [], "modifies": [], "deletes": []}

    @property
    def completion_criteria(self) -> list[str]:
        raw = self.plan.get("completion_criteria", [])
        if isinstance(raw, list):
            return raw
        if isinstance(raw, str) and raw.strip():
            return [raw.strip()]
        return []

    def touch(self) -> None:
        """Atualiza o timestamp de modificação do nó."""
        self.updated_at = datetime.now(timezone.utc)

    def to_dict(self) -> dict[str, Any]:
        """Serializa o StepNode para inspeção, logs e relatórios."""
        return {
            "id": self.id,
            "local_id": self.local_id,
            "parent_id": self.parent_id,
            "children_ids": list(self.children_ids),
            "depends_on": list(self.depends_on),
            "depth": self.depth,
            "role": self.role,
            "state": self.state.value,
            "plan": self.plan,
            "classification": self.classification,
            "decomposition_decision": self.decomposition_decision,
            "recomposition_contract": self.recomposition_contract,
            "result": self.result,
            "verification": self.verification,
            "error": self.error,
            "attempts": self.attempts,
        }


class StepGraph:
    """
    Grafo hierárquico e de dependências dos StepNodes de uma tarefa.

    Separa explicitamente a árvore de decomposição (parent_id / children_ids)
    das dependências de execução (depends_on).
    """

    ALLOWED_NODE_TRANSITIONS: dict[StepNodeState, set[StepNodeState]] = {
        StepNodeState.CREATED: {
            StepNodeState.CLASSIFIED,
            StepNodeState.DECOMPOSING,
            StepNodeState.READY,
            StepNodeState.FAILED,
            StepNodeState.CANCELLED,
        },
        StepNodeState.CLASSIFIED: {
            StepNodeState.DECOMPOSING,
            StepNodeState.READY,
            StepNodeState.FAILED,
            StepNodeState.CANCELLED,
        },
        StepNodeState.DECOMPOSING: {
            StepNodeState.READY,
            StepNodeState.BLOCKED,
            StepNodeState.FAILED,
            StepNodeState.CANCELLED,
        },
        StepNodeState.READY: {
            StepNodeState.RUNNING,
            StepNodeState.DECOMPOSING,
            StepNodeState.RECOMPOSING,
            StepNodeState.BLOCKED,
            StepNodeState.FAILED,
            StepNodeState.CANCELLED,
        },
        StepNodeState.RUNNING: {
            StepNodeState.VERIFYING,
            StepNodeState.RECOMPOSING,
            StepNodeState.COMPLETED,
            StepNodeState.BLOCKED,
            StepNodeState.FAILED,
            StepNodeState.CANCELLED,
        },
        StepNodeState.RECOMPOSING: {
            StepNodeState.VERIFYING,
            StepNodeState.COMPLETED,
            StepNodeState.BLOCKED,
            StepNodeState.FAILED,
            StepNodeState.CANCELLED,
        },
        StepNodeState.VERIFYING: {
            StepNodeState.RUNNING,
            StepNodeState.RECOMPOSING,
            StepNodeState.COMPLETED,
            StepNodeState.BLOCKED,
            StepNodeState.FAILED,
            StepNodeState.CANCELLED,
        },
        StepNodeState.BLOCKED: {
            StepNodeState.READY,
            StepNodeState.RUNNING,
            StepNodeState.FAILED,
            StepNodeState.CANCELLED,
        },
        StepNodeState.COMPLETED: {
            StepNodeState.RUNNING,
            StepNodeState.VERIFYING,
            StepNodeState.RECOMPOSING,
        },
        StepNodeState.FAILED: {
            StepNodeState.READY,
            StepNodeState.RUNNING,
        },
        StepNodeState.CANCELLED: set(),
    }

    def __init__(self) -> None:
        self.nodes: dict[str, StepNode] = {}
        self.root_ids: list[str] = []

    def add_node(self, node: StepNode) -> StepNode:
        """Registra um StepNode no grafo."""
        node_id = normalize_node_id(node.id)
        if node_id in self.nodes:
            raise ValueError(f"StepNode '{node_id}' já existe no grafo.")

        node.id = node_id
        self.nodes[node_id] = node

        if node.parent_id is None:
            self.root_ids.append(node_id)
        else:
            parent_id = normalize_node_id(node.parent_id)
            parent = self.get_node(parent_id)
            if node_id not in parent.children_ids:
                parent.children_ids.append(node_id)
            node.depth = parent.depth + 1

        return node

    def get_node(self, node_id: int | str) -> StepNode:
        """Obtém um StepNode pelo identificador."""
        key = normalize_node_id(node_id)
        if key not in self.nodes:
            raise KeyError(f"StepNode '{key}' não encontrado no grafo.")
        return self.nodes[key]

    def has_node(self, node_id: int | str) -> bool:
        """Verifica se um StepNode existe no grafo."""
        return normalize_node_id(node_id) in self.nodes

    def update_state(
        self,
        node_id: int | str,
        new_state: StepNodeState,
        *,
        error: str | None = None,
    ) -> StepNode:
        """Valida e aplica a transição de estado de um StepNode."""
        node = self.get_node(node_id)
        if new_state != node.state:
            allowed = self.ALLOWED_NODE_TRANSITIONS.get(node.state, set())
            if new_state not in allowed:
                raise ValueError(
                    f"Transição inválida no StepNode '{node.id}': "
                    f"{node.state.name} -> {new_state.name}"
                )
            node.state = new_state

        if error is not None:
            node.error = error
        elif new_state in (StepNodeState.READY, StepNodeState.COMPLETED):
            node.error = None

        node.touch()
        return node

    def get_children(self, node_id: int | str) -> list[StepNode]:
        """Retorna os filhos diretos de um StepNode."""
        node = self.get_node(node_id)
        return [self.get_node(child_id) for child_id in node.children_ids]

    def get_leaves(self, node_id: int | str | None = None) -> list[StepNode]:
        """
        Retorna os nós folha do grafo inteiro ou da subárvore de node_id.
        """
        if node_id is None:
            return [
                self.nodes[nid]
                for nid in self.nodes
                if self.nodes[nid].is_leaf
            ]

        node = self.get_node(node_id)
        if node.is_leaf:
            return [node]

        leaves: list[StepNode] = []
        for child_id in node.children_ids:
            leaves.extend(self.get_leaves(child_id))
        return leaves

    def get_dependencies(self, node_id: int | str) -> list[StepNode]:
        """Retorna as dependências diretas de um StepNode."""
        node = self.get_node(node_id)
        return [
            self.get_node(dep_id)
            for dep_id in node.depends_on
            if self.has_node(dep_id)
        ]

    def get_dependents(self, node_id: int | str) -> list[StepNode]:
        """Retorna os StepNodes que dependem diretamente do nó informado."""
        target_id = normalize_node_id(node_id)
        return [
            node
            for node in self.nodes.values()
            if target_id in node.depends_on
        ]

    def topological_order(
        self,
        node_ids: list[str] | None = None,
    ) -> list[str]:
        """
        Ordena um conjunto de nós respeitando suas dependências internas.

        Dependências fora do subconjunto informado são ignoradas na ordenação
        local (pressupõe-se que pertencem a escopos externos já resolvidos).
        """
        scope = list(node_ids) if node_ids is not None else list(self.root_ids)
        scope_set = {normalize_node_id(nid) for nid in scope}

        visiting: set[str] = set()
        visited: set[str] = set()
        ordered: list[str] = []

        def visit(current_id: str) -> None:
            if current_id in visiting:
                raise ValueError(
                    f"Ciclo de dependências detectado envolvendo '{current_id}'."
                )
            if current_id in visited:
                return

            visiting.add(current_id)
            node = self.get_node(current_id)

            for dep_id in node.depends_on:
                dep_key = normalize_node_id(dep_id)
                if dep_key in scope_set:
                    visit(dep_key)

            visiting.remove(current_id)
            visited.add(current_id)
            ordered.append(current_id)

        for nid in scope:
            key = normalize_node_id(nid)
            if key not in visited:
                visit(key)

        return ordered

    def to_dict(self) -> dict[str, Any]:
        """Serializa o grafo completo de StepNodes."""
        return {
            "root_ids": list(self.root_ids),
            "nodes": {
                node_id: node.to_dict()
                for node_id, node in self.nodes.items()
            },
        }
