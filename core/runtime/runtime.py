import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from core.agent.agent import Agent
from core.code_breaker.ast_recomposer import (
    Recomposer,
    strip_markdown_fences,
)
from core.code_breaker.composer import Composer
from core.models.step_node import StepGraph, StepNode, normalize_node_id
from core.pipeline.analyzer import ProjectAnalyzer
from core.pipeline.validator import PlanValidator, ResultVerifier
from core.state.states import StepNodeState, TaskState
from core.style.console import Console
from core.tools_management.tool_manager import (
    ToolClassifier,
    ToolRegistry,
    ToolType,
)


class ExecutionType(Enum):
    """Tipo de execução solicitada ao agente executor."""

    CREATE = "create"
    MODIFY = "modify"


console = Console()


def is_int(valor: str) -> bool:
    try:
        int(valor)
        return True
    except ValueError:
        return False


def parse_code(response: str) -> str:
    """Remove as cercas Markdown quando a resposta contém um bloco de código."""
    return strip_markdown_fences(response)


def iterative_union(execution_history: list | dict | None) -> set:
    """Retorna o conjunto de IDs referenciados em depends_on no histórico."""
    if isinstance(execution_history, dict):
        steps = execution_history.get("steps", {})
    elif isinstance(execution_history, (list, tuple, set)):
        steps = execution_history
    else:
        return set()

    depends_on = set()
    values = steps.values() if isinstance(steps, dict) else steps

    for step in values:
        if not isinstance(step, dict):
            continue
        dependencies = step.get("depends_on", [])

        if isinstance(dependencies, (list, tuple, set)):
            depends_on.update(dependencies)
        elif dependencies is not None:
            depends_on.add(dependencies)

    return depends_on


def search_registry(history: dict, key: str, target: Any):
    """Pesquisa registros de passos ou eventos no histórico de execução."""
    if not isinstance(history, dict):
        return None

    if key in ("step_id", "id"):
        steps = history.get("steps", {})
        if isinstance(steps, dict):
            step = steps.get(str(target))
            if isinstance(step, dict):
                return step

    events = history.get("events", [])
    if isinstance(events, list):
        for element in events:
            if isinstance(element, dict) and element.get(key) == target:
                return element

    return None


def search_depedents(conjunto: dict, step_id: int | str) -> set[str]:
    """Localiza os IDs dos passos que dependem do step_id informado."""
    dependents: set[str] = set()
    steps = conjunto.get("steps", {})

    if not isinstance(steps, dict):
        return dependents

    for dependent_id, node in steps.items():
        if not isinstance(node, dict):
            continue

        dependencies = node.get("depends_on", [])
        if not isinstance(dependencies, (list, tuple, set)):
            continue

        if any(str(dep_id) == str(step_id) for dep_id in dependencies):
            dependents.add(str(dependent_id))

    return dependents


def execution_messages_by_type(
    exec_type: ExecutionType,
    context: dict[str, Any],
) -> list[dict[str, str]]:
    """Constrói as mensagens de prompt para execução ou revisão de um StepNode."""
    match exec_type:
        case ExecutionType.CREATE:
            current_step = context["current_step"]["id"]
            role_hint = context["current_step"].get("role")
            role_instruction = (
                f"Você está produzindo especificamente o membro de papel '{role_hint}' "
                "para posterior recomposição por AST no artefato pai. "
                if role_hint
                else ""
            )
            effects = context["current_step"].get("effects", {})
            has_file_output = bool(
                effects.get("creates") or effects.get("modifies")
            )
            output_instruction = (
                "Se a etapa gerar código ou conteúdo de arquivo, retorne "
                "exclusivamente o conteúdo completo do arquivo (sem prosa antes ou depois). "
                if has_file_output
                else ""
            )

            return [
                {
                    "role": "system",
                    "content": (
                        "Você é o agente executor do Atom. "
                        "Sua responsabilidade é produzir exclusivamente o resultado "
                        "solicitado no StepNode atual, respeitando seus contratos, "
                        "efeitos esperados e critérios de conclusão. "
                        f"{role_instruction}"
                        f"{output_instruction}"
                        "Use os resultados das dependências como referência e "
                        "respeite as restrições do objetivo original. "
                        "Não execute nem descreva etapas futuras. "
                        f"Realize exclusivamente a tarefa da etapa: {current_step}. "
                        "Não inclua explicações desnecessárias. "
                        "Não afirme que realizou ações externas, salvou arquivos "
                        "ou executou código se isso não ocorreu."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Execute o StepNode descrito no contexto abaixo:\n\n"
                        + json.dumps(context, ensure_ascii=False, indent=2)
                    ),
                },
            ]

        case ExecutionType.MODIFY:
            return [
                {
                    "role": "system",
                    "content": (
                        "Você é o agente revisor e corretor do Atom.\n\n"
                        "Sua responsabilidade é revisar e corrigir o resultado "
                        "de um StepNode já executado, considerando o objetivo original, "
                        "os contratos, os critérios de conclusão, eventuais falhas "
                        "detectadas na verificação e os resultados das etapas dependentes.\n\n"
                        "REGRAS DE REVISÃO:\n"
                        "1. Identifique inconsistências, omissões, erros sintáticos ou "
                        "incompatibilidades com os critérios de conclusão.\n"
                        "2. Garanta compatibilidade com as etapas dependentes.\n"
                        "3. Corrija apenas o necessário, preservando o conteúdo válido.\n"
                        "4. Forneça a versão corrigida completa do artefato ou fragmento, "
                        "sem apenas sugestões.\n"
                        "5. Não afirme que executou ações externas que não ocorreram.\n\n"
                        "FORMATO DA RESPOSTA:\n"
                        "Retorne apenas o resultado revisado da etapa."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Revise o resultado existente do StepNode abaixo e corrija "
                        "os problemas encontrados.\n\n"
                        "CONTEXTO DA REVISÃO:\n\n"
                        + json.dumps(context, ensure_ascii=False, indent=2)
                    ),
                },
            ]

        case _:
            raise ValueError(
                "Resultado de enum inválido para execution_messages_by_type."
            )


@dataclass
class Task:
    """Representa uma tarefa gerenciada pelo Atom e seu grafo de StepNodes."""

    goal: str
    id: str = field(default_factory=lambda: str(uuid4()))
    state: TaskState = TaskState.CREATED
    plan_proposal: dict | None = None

    total_steps: int | None = None
    current_steps: int | None = None

    step_graph: StepGraph = field(default_factory=StepGraph)
    task_context: dict | None = None
    execution_history: dict | None = None
    final_report: dict | None = None

    error: str | None = None
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class Runtime:
    """
    Coordena o pipeline completo de execução híbrida do Atom.

    Orquestra análise de projeto, planejamento, validação determinística,
    classificação discriminativa (Laya), decomposição/recomposição (Code Breaker),
    execução controlada, verificação e relatório final.
    """

    def __init__(
        self,
        agent: Agent | None = None,
        *,
        classifier: ToolClassifier | None = None,
        registry: ToolRegistry | None = None,
        workspace_root: str | Path | None = None,
        apply_effects: bool = False,
        max_retries: int = 2,
    ) -> None:
        self.agent = agent if agent is not None else Agent()
        self.registry = (
            registry
            if registry is not None
            else ToolRegistry(workspace_root=workspace_root)
        )
        self.classifier = (
            classifier
            if classifier is not None
            else ToolClassifier(test_mode=self.agent.test_mode)
        )
        self.analyzer = ProjectAnalyzer(
            workspace_root=self.registry.workspace_root
        )
        self.plan_validator = PlanValidator(registry=self.registry)
        self.result_verifier = ResultVerifier(
            agent=self.agent,
            classifier=self.classifier,
        )
        self.composer = Composer(
            agent=self.agent,
            classifier=self.classifier,
        )
        self.recomposer = Recomposer()
        self.apply_effects = apply_effects
        self.max_retries = max_retries

    def _transition(self, task: Task, new_state: TaskState) -> None:
        """Valida e aplica uma transição de estado da Task."""
        allowed_transitions = {
            TaskState.CREATED: {
                TaskState.PLANNING,
                TaskState.CANCELLED,
            },
            TaskState.PLANNING: {
                TaskState.READY,
                TaskState.BLOCKED,
                TaskState.FAILED,
                TaskState.CANCELLED,
            },
            TaskState.READY: {
                TaskState.RUNNING,
                TaskState.BLOCKED,
                TaskState.FAILED,
                TaskState.CANCELLED,
            },
            TaskState.RUNNING: {
                TaskState.BLOCKED,
                TaskState.COMPLETED,
                TaskState.FAILED,
                TaskState.CANCELLED,
            },
            TaskState.BLOCKED: {
                TaskState.PLANNING,
                TaskState.READY,
                TaskState.RUNNING,
                TaskState.FAILED,
                TaskState.CANCELLED,
            },
            TaskState.COMPLETED: set(),
            TaskState.FAILED: set(),
            TaskState.CANCELLED: set(),
        }

        if new_state not in allowed_transitions[task.state]:
            raise ValueError(
                f"Transição inválida: {task.state.name} -> {new_state.name}"
            )

        task.state = new_state

    def _ensure_history(self, task: Task) -> dict[str, Any]:
        """Garante a estrutura básica do histórico de execução da tarefa."""
        if task.execution_history is None:
            task.execution_history = {
                "events": [],
                "steps": {},
                "artifacts": {},
            }
        task.execution_history.setdefault("events", [])
        task.execution_history.setdefault("steps", {})
        task.execution_history.setdefault("artifacts", {})
        return task.execution_history

    def add_context_history(
        self,
        task: Task,
        event_type: str,
        summary: str,
        *,
        status: str = "info",
        step_id: int | str | None = None,
        details: dict | None = None,
    ) -> None:
        """Registra um acontecimento no histórico de execução da tarefa."""
        history = self._ensure_history(task)

        event: dict[str, Any] = {
            "type": event_type,
            "status": status,
            "summary": summary,
            "step_id": step_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        if details is not None:
            event["details"] = details

        history["events"].append(event)

    # ========================================================================
    # Etapa 1: Inspeção do projeto (Analisador)
    # ========================================================================

    def inspect_project(self, task: Task) -> Task:
        """Coleta fatos atuais do projeto para contextualizar o planejamento."""
        console.log("🔍 Inspecionando o projeto..")
        project_snapshot = self.analyzer.inspect()

        if task.task_context is None:
            task.task_context = {}

        task.task_context["project"] = project_snapshot
        task.task_context["available_tools"] = self.registry.list_tools()

        self.add_context_history(
            task,
            "project_inspected",
            "Estrutura inicial do projeto inspecionada.",
            status="success",
            details={
                "files_count": len(project_snapshot.get("files", [])),
                "directories_count": len(
                    project_snapshot.get("directories", [])
                ),
            },
        )
        return task

    # ========================================================================
    # Etapas 2 e 3: Planejamento e Validação Determinística
    # ========================================================================

    def create_task(self, goal: str) -> Task:
        """Cria uma tarefa sem executá-la."""
        if not isinstance(goal, str) or not goal.strip():
            raise ValueError("O objetivo da tarefa não pode ser vazio.")

        return Task(goal=goal.strip())

    def plan_task(self, task: Task) -> Task:
        """Solicita ao modelo um plano estruturado, valida-o e constrói o grafo de StepNodes."""
        if task.state not in (TaskState.CREATED, TaskState.BLOCKED):
            raise ValueError(
                f"A tarefa não pode ser planejada no estado {task.state.name}."
            )

        if task.task_context is None:
            self.inspect_project(task)

        self._transition(task, TaskState.PLANNING)

        plan_example = {
            "steps": [
                {
                    "id": 1,
                    "description": "Criar a interface FiguraGeometrica",
                    "objective": "Definir o contrato comum das figuras geométricas",
                    "depends_on": [],
                    "contracts": {
                        "preconditions": [],
                        "postconditions": [
                            "A interface FiguraGeometrica deve existir",
                            "A interface deve declarar o método calcularArea",
                        ],
                        "invariants": [],
                    },
                    "effects": {
                        "reads": [],
                        "creates": ["FiguraGeometrica.java"],
                        "modifies": [],
                        "deletes": [],
                    },
                    "completion_criteria": [
                        "Arquivo criado",
                        "Interface compilando corretamente",
                    ],
                    "decomposition": {
                        "is_divisible": False,
                        "subtasks": [],
                    },
                }
            ]
        }

        messages = [
            {
                "role": "system",
                "content": (
                    "Você é o agente de planejamento do Atom. "
                    "Analise o objetivo e o contexto do projeto e divida a tarefa "
                    "em etapas claras, ordenadas e verificáveis.\n"
                    "Não afirme que executou ações.\n"
                    "Não inclua instalações de pacotes externos.\n"
                    "Não escreva código-fonte dentro do plano.\n"
                    "Retorne EXCLUSIVAMENTE um objeto JSON válido, sem Markdown ou "
                    "texto adicional, seguindo exatamente este esquema:\n"
                    + json.dumps(plan_example, ensure_ascii=False, indent=2)
                    + "\nREGRAS:\n"
                    "- Os IDs devem começar em 1 e ser inteiros sequenciais.\n"
                    "- Cada passo deve possuir: id, description, objective, "
                    "depends_on, contracts (preconditions, postconditions, invariants), "
                    "effects (reads, creates, modifies, deletes), "
                    "completion_criteria (lista de strings) e "
                    "decomposition (is_divisible, subtasks).\n"
                    "- Não crie dependências circulares nem referências inexistentes."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Objetivo da tarefa:\n{task.goal}\n\n"
                    "Contexto do projeto:\n"
                    + json.dumps(task.task_context or {}, ensure_ascii=False, indent=2)
                ),
            },
        ]

        try:
            console.log("⚙️  Planejando tarefa..")
            response = self.agent.send(messages)

            if not isinstance(response, str) or not response.strip():
                raise ValueError("O agente retornou um plano vazio ou inválido.")

            plan = json.loads(parse_code(response))
            validated_plan = self.plan_validator.validate(plan)

            # Constrói o grafo de StepNodes da Task
            graph = StepGraph()
            for step in validated_plan["steps"]:
                node_id = normalize_node_id(step["id"])
                node = StepNode(
                    id=node_id,
                    local_id=step["id"],
                    plan=step,
                    depends_on=[
                        normalize_node_id(dep) for dep in step["depends_on"]
                    ],
                    state=StepNodeState.CREATED,
                )
                graph.add_node(node)

            task.plan_proposal = validated_plan
            task.step_graph = graph
            task.total_steps = len(validated_plan["steps"])
            task.current_steps = 1
            task.error = None

            self.add_context_history(
                task,
                "plan_validated",
                f"Plano validado com {task.total_steps} StepNodes.",
                status="success",
            )

            self._transition(task, TaskState.READY)
            return task

        except Exception as error:
            task.error = str(error)
            self.add_context_history(
                task,
                "planning_failed",
                f"Falha ao planejar tarefa: {error}",
                status="error",
            )
            console.error(f"Erro ao criar o planejamento inicial: {error}")
            self._transition(task, TaskState.FAILED)
            return task

    # ========================================================================
    # Etapa 3 da Orquestração: Classificação Discriminativa (Laya)
    # ========================================================================

    def classify_steps(self, task: Task) -> Task:
        """
        Classifica cada StepNode raiz usando o modelo discriminativo Laya e
        atualiza a dimensão `classification` e o estado do nó.
        """
        console.log("🏷️  Classificando StepNodes com modelo discriminativo..")

        for node_id in task.step_graph.root_ids:
            node = task.step_graph.get_node(node_id)
            classification = self.classifier.classify(
                f"{node.description}. Objetivo: {node.objective}",
                effects=node.effects,
            )
            node.classification = classification
            task.step_graph.update_state(node.id, StepNodeState.CLASSIFIED)

            self.add_context_history(
                task,
                "step_classified",
                (
                    f"StepNode '{node.id}' classificado como "
                    f"'{classification['choice']}' ({classification['tool_type']})."
                ),
                status="info",
                step_id=node.id,
                details=classification,
            )

        return task

    # ========================================================================
    # Code Breaker (Composer): Decomposição de StepNodes
    # ========================================================================

    def decompose_steps(self, task: Task) -> Task:
        """
        Submete cada StepNode raiz ao Composer do Code Breaker para decidir
        se precisa ser decomposto e registrar seu contrato de recomposição.
        """
        console.log("🧩 Avaliando decomposição dos StepNodes (Composer)..")

        for node_id in list(task.step_graph.root_ids):
            node = task.step_graph.get_node(node_id)
            children = self.composer.decompose_node(
                task.step_graph,
                node,
                goal=task.goal,
            )

            self.add_context_history(
                task,
                "step_decomposition_evaluated",
                (
                    f"StepNode '{node.id}' decomposto em {len(children)} filhos."
                    if children
                    else f"StepNode '{node.id}' mantido para execução direta."
                ),
                status="info",
                step_id=node.id,
                details={
                    "decision": node.decomposition_decision,
                    "children_ids": [c.id for c in children],
                    "has_recomposition_contract": (
                        node.recomposition_contract is not None
                    ),
                },
            )

        return task

    # ========================================================================
    # Montagem de contexto e compatibilidade com métodos existentes
    # ========================================================================

    def slice_step(self, task: Task, step: int | str) -> dict:
        """Seleciona os dados de um passo pelo número ou ID do StepNode."""
        if task.step_graph.nodes and task.step_graph.has_node(step):
            return task.step_graph.get_node(step).plan

        if task.plan_proposal is None:
            raise ValueError("A tarefa não possui um plano.")

        steps = task.plan_proposal["steps"]
        step_int = int(step)
        if not 1 <= step_int <= len(steps):
            raise ValueError("Número do passo fora do intervalo válido.")

        return steps[step_int - 1]

    def build_execution_context(self, task: Task, step: dict) -> dict:
        """Monta o contexto com os resultados das dependências e ancestrais."""
        if not task.plan_proposal:
            raise ValueError("A tarefa ainda não possui um plano.")

        planned_steps = task.plan_proposal.get("steps", [])
        if not isinstance(planned_steps, list):
            raise ValueError("O plano possui uma lista de passos inválida.")

        steps_by_id = {planned["id"]: planned for planned in planned_steps}
        step_id = step.get("id")
        if step_id not in steps_by_id:
            raise ValueError(
                f"A etapa {step_id} não pertence ao plano da tarefa."
            )

        current_step = steps_by_id[step_id]
        history = task.execution_history or {}
        recorded_steps = history.get("steps", {})

        dependencies = []
        visited = set()

        def collect_dependencies(current_id: int) -> None:
            current = steps_by_id[current_id]
            for dependency_id in current.get("depends_on", []):
                if dependency_id in visited:
                    continue
                if dependency_id not in steps_by_id:
                    raise ValueError(
                        f"A etapa {current_id} referencia a dependência "
                        f"inexistente {dependency_id}."
                    )

                visited.add(dependency_id)
                collect_dependencies(dependency_id)

                record = recorded_steps.get(str(dependency_id))
                if record is None:
                    raise ValueError(
                        f"A etapa {current_id} depende da etapa "
                        f"{dependency_id}, que ainda não possui resultado."
                    )

                result = record.get("result")
                if not isinstance(result, str) or not result.strip():
                    raise ValueError(
                        f"A etapa {dependency_id} não possui "
                        "um resultado textual válido."
                    )

                dependencies.append(
                    {
                        "step_id": dependency_id,
                        "description": record.get("description"),
                        "result": result,
                    }
                )

        if not isinstance(step_id, int):
            raise ValueError(
                f"O step_id não é um inteiro válido. Valor de step_id: {step_id}"
            )

        collect_dependencies(step_id)

        return {
            "goal": task.goal,
            "task_context": task.task_context or {},
            "current_step": {
                "id": current_step["id"],
                "description": current_step["description"],
                "objective": current_step.get("objective", ""),
                "contracts": current_step.get("contracts", {}),
                "effects": current_step.get("effects", {}),
                "completion_criteria": current_step.get(
                    "completion_criteria", []
                ),
            },
            "dependencies": dependencies,
        }

    def build_node_context(
        self,
        task: Task,
        node: StepNode,
        exec_type: ExecutionType,
        *,
        issues: list[str] | None = None,
    ) -> dict[str, Any]:
        """Monta o contexto completo para execução ou revisão de um StepNode."""
        if exec_type == ExecutionType.MODIFY:
            dependents = [
                {
                    "id": dep.id,
                    "description": dep.description,
                    "completion_criteria": dep.completion_criteria,
                    "result": dep.result or "",
                }
                for dep in task.step_graph.get_dependents(node.id)
                if dep.result
            ]
            return {
                "goal": task.goal,
                "task_context": task.task_context or {},
                "current_step": {
                    "id": node.id,
                    "role": node.role,
                    "description": node.description,
                    "objective": node.objective,
                    "contracts": node.contracts,
                    "effects": node.effects,
                    "completion_criteria": node.completion_criteria,
                    "previous_result": node.result or "",
                },
                "verification_issues": issues or [],
                "dependents": dependents,
            }

        dependencies: list[dict[str, Any]] = []
        visited: set[str] = set()

        def collect_node_deps(current_id: str) -> None:
            current = task.step_graph.get_node(current_id)
            for dep_id in current.depends_on:
                if dep_id in visited:
                    continue
                visited.add(dep_id)
                collect_node_deps(dep_id)
                dep_node = task.step_graph.get_node(dep_id)
                if not isinstance(dep_node.result, str) or not dep_node.result.strip():
                    raise ValueError(
                        f"StepNode '{current_id}' depende de '{dep_id}', "
                        "que ainda não possui resultado válido."
                    )
                dependencies.append(
                    {
                        "step_id": dep_node.id,
                        "role": dep_node.role,
                        "description": dep_node.description,
                        "result": dep_node.result,
                    }
                )

        collect_node_deps(node.id)

        # Se o nó é filho, inclui também dependências declaradas no nó pai
        if node.parent_id is not None:
            parent_node = task.step_graph.get_node(node.parent_id)
            for parent_dep_id in parent_node.depends_on:
                if parent_dep_id in visited:
                    continue
                visited.add(parent_dep_id)
                dep_node = task.step_graph.get_node(parent_dep_id)
                if dep_node.result:
                    dependencies.append(
                        {
                            "step_id": dep_node.id,
                            "description": dep_node.description,
                            "result": dep_node.result,
                        }
                    )

        parent_contract = (
            task.step_graph.get_node(node.parent_id).recomposition_contract
            if node.parent_id is not None
            else None
        )

        return {
            "goal": task.goal,
            "task_context": task.task_context or {},
            "current_step": {
                "id": node.id,
                "role": node.role,
                "description": node.description,
                "objective": node.objective,
                "classification": node.classification,
                "contracts": node.contracts,
                "effects": node.effects,
                "completion_criteria": node.completion_criteria,
            },
            "parent_recomposition_contract": parent_contract,
            "dependencies": dependencies,
        }

    def context_by_depedence(self, task: Task, step: dict) -> dict[str, Any]:
        """Monta contexto de revisão considerando passos dependentes no histórico."""
        step_id = step["id"]
        history = task.execution_history or {}
        steps = history.get("steps", {})
        current_record = steps.get(str(step_id), {})
        dependents_ids = search_depedents(history, step_id)

        dependents = [
            {
                "id": dependent_id,
                "description": steps[str(dependent_id)].get("description", ""),
                "completion_criteria": steps[str(dependent_id)].get(
                    "completion_criteria", []
                ),
                "result": steps[str(dependent_id)].get("result", ""),
            }
            for dependent_id in sorted(dependents_ids)
            if str(dependent_id) in steps
        ]

        return {
            "goal": task.goal,
            "task_context": task.task_context or {},
            "current_step": {
                "id": step_id,
                "description": step["description"],
                "completion_criteria": step.get("completion_criteria", []),
                "previous_result": current_record.get("result", ""),
            },
            "dependents": dependents,
        }

    def solve_context(
        self,
        task: Task,
        step: dict,
        exec_type: ExecutionType,
    ) -> dict[str, Any]:
        """Mapper para montar o contexto de acordo com o tipo de execução."""
        match exec_type:
            case ExecutionType.CREATE:
                return self.build_execution_context(task, step)
            case ExecutionType.MODIFY:
                return self.context_by_depedence(task, step)

    # ========================================================================
    # Etapas 4, 5, 6 e 7: Execução, Recomposição AST, Verificação e Correção
    # ========================================================================

    def execute(
        self,
        task: Task,
        step: dict,
        exec_type: ExecutionType,
    ) -> str | None:
        """Solicita ao agente a execução de um passo do plano."""
        step_id = step["id"]
        if task.step_graph.has_node(step_id):
            return self.execute_node(task, str(step_id), exec_type)

        current_goal = step["description"]
        completion_criteria = step.get("completion_criteria", [])
        depends_on = step.get("depends_on", [])

        self._ensure_history(task)
        self.add_context_history(
            task,
            "step_execution_started",
            f"Execução da etapa {step_id} iniciada.",
            step_id=step_id,
        )

        try:
            context = self.solve_context(task, step, exec_type)
            messages = execution_messages_by_type(exec_type, context)
            result = self.agent.send(messages)

            if not isinstance(result, str) or not result.strip():
                raise ValueError(
                    "O agente retornou um resultado vazio ou inválido."
                )

            result = result.strip()
            task.execution_history["steps"][str(step_id)] = {
                "status": "result_generated",
                "description": current_goal,
                "completion_criteria": completion_criteria,
                "result": result,
                "depends_on": depends_on,
            }

            self.add_context_history(
                task,
                "step_result_generated",
                f"Resultado gerado para a etapa {step_id}.",
                status="success",
                step_id=step_id,
            )
            return result

        except Exception as error:
            self.add_context_history(
                task,
                "step_execution_failed",
                f"Falha durante a execução da etapa {step_id}.",
                status="error",
                step_id=step_id,
                details={"error": str(error)},
            )
            console.error(f"Erro ao executar a etapa: {error}")
            return None

    def execute_node(
        self,
        task: Task,
        node_id: str,
        exec_type: ExecutionType = ExecutionType.CREATE,
        *,
        issues: list[str] | None = None,
    ) -> str | None:
        """Executa um StepNode folha e atualiza seu estado e histórico."""
        node = task.step_graph.get_node(node_id)
        if not node.is_leaf:
            raise ValueError(
                f"StepNode '{node.id}' possui filhos; execução direta não permitida."
            )

        self._ensure_history(task)
        task.step_graph.update_state(node.id, StepNodeState.RUNNING)
        node.attempts += 1

        self.add_context_history(
            task,
            "step_execution_started",
            f"Execução do StepNode '{node.id}' iniciada (tentativa {node.attempts}).",
            step_id=node.id,
        )

        try:
            context = self.build_node_context(
                task,
                node,
                exec_type,
                issues=issues,
            )
            messages = execution_messages_by_type(exec_type, context)
            raw_result = self.agent.send(messages)

            if not isinstance(raw_result, str) or not raw_result.strip():
                raise ValueError(
                    f"O agente retornou resultado vazio para StepNode '{node.id}'."
                )

            node.result = raw_result.strip()
            node.touch()

            self._record_step_output(task, node)
            self._maybe_apply_tool_effects(task, node)

            self.add_context_history(
                task,
                "step_result_generated",
                f"Resultado gerado para o StepNode '{node.id}'.",
                status="success",
                step_id=node.id,
            )
            return node.result

        except Exception as error:
            task.step_graph.update_state(
                node.id,
                StepNodeState.FAILED,
                error=str(error),
            )
            self.add_context_history(
                task,
                "step_execution_failed",
                f"Falha durante a execução do StepNode '{node.id}': {error}",
                status="error",
                step_id=node.id,
                details={"error": str(error)},
            )
            console.error(f"Erro ao executar StepNode '{node.id}': {error}")
            return None

    def recompose_node(self, task: Task, parent_id: str) -> str:
        """
        Executa a recomposição AST de um StepNode pai a partir de seus filhos
        usando o container Recomposer do Code Breaker.
        """
        parent = task.step_graph.get_node(parent_id)
        children = task.step_graph.get_children(parent.id)

        task.step_graph.update_state(parent.id, StepNodeState.RECOMPOSING)
        console.log(f"🧬 Recompondo StepNode '{parent.id}' via AST..")

        reconstructed = self.recomposer.recompose(parent, children)
        parent.result = reconstructed
        parent.touch()

        self._record_step_output(task, parent)
        self._maybe_apply_tool_effects(task, parent)

        self.add_context_history(
            task,
            "step_recomposed",
            f"StepNode '{parent.id}' recomposto via AST.",
            status="success",
            step_id=parent.id,
            details={
                "artifact": (parent.recomposition_contract or {}).get("artifact"),
                "children_ids": [c.id for c in children],
            },
        )
        return reconstructed

    def verify_and_correct_node(
        self,
        task: Task,
        node_id: str,
        *,
        run_semantic_check: bool = True,
    ) -> bool:
        """
        Verifica um StepNode (folha ou recomposto) e executa correções até o
        limite de tentativas definido em `self.max_retries`.
        """
        node = task.step_graph.get_node(node_id)

        for attempt in range(self.max_retries + 1):
            task.step_graph.update_state(node.id, StepNodeState.VERIFYING)
            verification = self.result_verifier.verify_node(
                task.step_graph,
                node,
                goal=task.goal,
                plan_proposal=task.plan_proposal,
                run_semantic_check=run_semantic_check,
            )

            self.add_context_history(
                task,
                "step_verified",
                (
                    f"StepNode '{node.id}' aprovado na verificação."
                    if verification["passed"]
                    else f"StepNode '{node.id}' reprovado na verificação."
                ),
                status="success" if verification["passed"] else "warning",
                step_id=node.id,
                details=verification,
            )

            if verification["passed"]:
                task.step_graph.update_state(node.id, StepNodeState.COMPLETED)
                return True

            if attempt >= self.max_retries:
                break

            issues = verification.get("issues", [])
            console.warn(
                f"Corrigindo StepNode '{node.id}' (tentativa {attempt + 1}/{self.max_retries})"
            )

            if node.is_leaf:
                revised = self.execute_node(
                    task,
                    node.id,
                    ExecutionType.MODIFY,
                    issues=issues,
                )
                if revised is None:
                    break
            else:
                # Reexecuta a recomposição caso os filhos tenham sido ajustados
                try:
                    self.recompose_node(task, node.id)
                except Exception as error:
                    node.error = str(error)
                    break

        task.step_graph.update_state(
            node.id,
            StepNodeState.FAILED,
            error="; ".join((node.verification or {}).get("issues", [])),
        )
        return False

    def _execute_subtree(self, task: Task, node_id: str) -> bool:
        """
        Executa um StepNode respeitando delegação aos filhos e verificação do pai.
        """
        node = task.step_graph.get_node(node_id)

        if node.is_leaf:
            result = self.execute_node(task, node.id, ExecutionType.CREATE)
            if result is None:
                return False
            return self.verify_and_correct_node(
                task,
                node.id,
                run_semantic_check=False,
            )

        # Nó pai: delega execução aos filhos em ordem topológica
        task.step_graph.update_state(node.id, StepNodeState.RUNNING)
        ordered_children = task.step_graph.topological_order(node.children_ids)

        for child_id in ordered_children:
            ok = self._execute_subtree(task, child_id)
            if not ok:
                task.step_graph.update_state(
                    node.id,
                    StepNodeState.FAILED,
                    error=f"Falha no StepNode filho '{child_id}'.",
                )
                return False

        try:
            self.recompose_node(task, node.id)
        except Exception as error:
            task.step_graph.update_state(
                node.id,
                StepNodeState.FAILED,
                error=f"Falha na recomposição AST: {error}",
            )
            self.add_context_history(
                task,
                "recomposition_failed",
                f"Falha ao recompor StepNode '{node.id}': {error}",
                status="error",
                step_id=node.id,
            )
            console.error(f"Erro ao recompor StepNode '{node.id}': {error}")
            return False

        # Verificação obrigatória do pai (integração e contrato)
        return self.verify_and_correct_node(
            task,
            node.id,
            run_semantic_check=True,
        )

    def _record_step_output(self, task: Task, node: StepNode) -> None:
        """Registra resultado e artefatos produzidos pelo StepNode no histórico."""
        history = self._ensure_history(task)
        history["steps"][node.id] = {
            "status": node.state.value,
            "description": node.description,
            "objective": node.objective,
            "completion_criteria": node.completion_criteria,
            "depends_on": list(node.depends_on),
            "classification": node.classification,
            "result": node.result or "",
        }

        artifact_name = None
        if isinstance(node.recomposition_contract, dict):
            artifact_name = node.recomposition_contract.get("artifact")
        elif node.effects.get("creates"):
            artifact_name = node.effects["creates"][0]
        elif node.effects.get("modifies"):
            artifact_name = node.effects["modifies"][0]

        if artifact_name and node.result:
            history["artifacts"][str(artifact_name)] = {
                "source_node": node.id,
                "content": node.result,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

    def _find_tool(
        self,
        tool_type: ToolType,
        path_suffix: str,
    ):
        """Localiza uma ferramenta específica no ToolRegistry pelo sufixo."""
        candidates = self.registry.find_by_type(tool_type)
        for tool in candidates:
            if tool.path.endswith(path_suffix):
                return tool
        return candidates[0] if candidates else None

    @staticmethod
    def _is_directory_target(target_path: str, node: StepNode) -> bool:
        """Determina se um alvo de efeito representa um diretório."""
        cleaned = str(target_path).strip()
        if cleaned.endswith("/"):
            return True
        if Path(cleaned).suffix:
            return False
        context_text = f"{node.description} {node.objective}".lower()
        return any(
            word in context_text
            for word in ("diretór", "diretor", "pasta", "pastas", "directory", "folder")
        )

    def _run_registry_tool(
        self,
        task: Task,
        node: StepNode,
        tool: Any,
        args: list[str],
        target_label: str,
    ) -> None:
        """Executa uma ferramenta do ToolRegistry e registra no histórico."""
        if tool is None:
            return
        outcome = self.registry.execute_tool(tool.id, args)
        self.add_context_history(
            task,
            "tool_executed",
            f"Ferramenta '{tool.path}' aplicada em '{target_label}'.",
            status="success" if outcome is not None else "error",
            step_id=node.id,
        )

    def _maybe_apply_tool_effects(self, task: Task, node: StepNode) -> None:
        """
        Quando `self.apply_effects` está ativo, persiste efeitos no workspace
        exclusivamente por meio das ferramentas autorizadas do ToolRegistry.
        """
        if not self.apply_effects or not node.result:
            return

        # Apenas nós folha sem recomposição ou nós pai já recompostos escrevem artefatos
        if node.parent_id is not None and node.is_leaf:
            parent = task.step_graph.get_node(node.parent_id)
            if parent.recomposition_contract is not None:
                return

        create_dir_tool = self._find_tool(ToolType.CREATE, "create_directory.sh")
        create_file_tool = self._find_tool(ToolType.CREATE, "create_file.sh")
        write_tool = self._find_tool(ToolType.UPDATE, "write_file.sh")
        delete_file_tool = self._find_tool(ToolType.DELETE, "delete_archive.sh")
        delete_dir_tool = self._find_tool(ToolType.DELETE, "delete_directory.sh")
        read_file_tool = self._find_tool(ToolType.READ, "read_archive.sh")
        list_dir_tool = self._find_tool(ToolType.READ, "list_archives.sh")

        content = strip_markdown_fences(node.result)

        # Se o nó foi recomposto por AST, o contrato define o artefato único final
        if isinstance(node.recomposition_contract, dict):
            artifact = node.recomposition_contract.get("artifact")
            if isinstance(artifact, str) and artifact.strip():
                target = artifact.strip()
                self._run_registry_tool(
                    task, node, create_file_tool, [target], target
                )
                self._run_registry_tool(
                    task, node, write_tool, [content, target], target
                )
                return

        creates = [str(p).strip() for p in node.effects.get("creates", []) if str(p).strip()]
        modifies = [str(p).strip() for p in node.effects.get("modifies", []) if str(p).strip()]
        deletes = [str(p).strip() for p in node.effects.get("deletes", []) if str(p).strip()]
        reads = [str(p).strip() for p in node.effects.get("reads", []) if str(p).strip()]

        file_creates: list[str] = []
        for target_path in creates:
            if self._is_directory_target(target_path, node):
                dir_arg = target_path.rstrip("/") or target_path
                self._run_registry_tool(
                    task, node, create_dir_tool, [dir_arg], target_path
                )
            else:
                file_creates.append(target_path)
                self._run_registry_tool(
                    task, node, create_file_tool, [target_path], target_path
                )

        if len(file_creates) == 1:
            self._run_registry_tool(
                task,
                node,
                write_tool,
                [content, file_creates[0]],
                file_creates[0],
            )

        if len(modifies) == 1:
            self._run_registry_tool(
                task,
                node,
                write_tool,
                [content, modifies[0]],
                modifies[0],
            )
        elif len(modifies) > 1 and not file_creates:
            for target_path in modifies:
                self._run_registry_tool(
                    task,
                    node,
                    write_tool,
                    [content, target_path],
                    target_path,
                )

        for target_path in deletes:
            resolved = self.registry.validate_workspace_path(target_path)
            if target_path.endswith("/") or resolved.is_dir():
                dir_arg = target_path.rstrip("/") or target_path
                if resolved.exists():
                    self._run_registry_tool(
                        task, node, delete_dir_tool, [dir_arg], target_path
                    )
            elif resolved.exists() or resolved.is_symlink():
                self._run_registry_tool(
                    task, node, delete_file_tool, [target_path], target_path
                )

        if not creates and not modifies and not deletes and reads:
            choice = (node.classification or {}).get("choice")
            if choice == "read":
                for target_path in reads:
                    resolved = self.registry.validate_workspace_path(target_path)
                    if resolved.is_dir():
                        self._run_registry_tool(
                            task, node, list_dir_tool, [target_path], target_path
                        )
                    elif resolved.is_file():
                        self._run_registry_tool(
                            task, node, read_file_tool, [target_path], target_path
                        )

    def inspect(self, task: Task, step_number: int | str) -> bool:
        """Verifica a integridade de um passo em relação aos seus dependentes."""
        console.log(f"Verificando integridade do passo {step_number}")
        node_key = normalize_node_id(step_number)

        if task.step_graph.has_node(node_key):
            return self.verify_and_correct_node(
                task,
                node_key,
                run_semantic_check=True,
            )

        try:
            history = task.execution_history
            if not isinstance(history, dict):
                raise TypeError("O histórico de execução não é um dicionário.")

            steps = history.get("steps")
            if not isinstance(steps, dict):
                raise TypeError(
                    "O histórico não contém um dicionário válido de passos."
                )

            step = steps.get(str(step_number))
            if not isinstance(step, dict):
                raise KeyError(
                    f"Passo {step_number} não encontrado no histórico."
                )

            step_result = step.get("result")
            if not isinstance(step_result, str) or not step_result.strip():
                raise ValueError(
                    f"O passo {step_number} não possui um resultado válido."
                )

            dependents = search_depedents(history, step_number)
            another_results = []
            for dependent_id in sorted(dependents):
                dependent = steps.get(str(dependent_id))
                if not isinstance(dependent, dict):
                    raise KeyError(
                        f"Passo dependente {dependent_id} não encontrado."
                    )
                another_results.append(
                    {
                        "step_id": dependent_id,
                        "description": dependent.get("description", ""),
                        "result": dependent.get("result", ""),
                    }
                )

            dependents_summary = "\n".join(
                f"- Passo {dep['step_id']} ({dep['description']}): {str(dep['result'])[:220]}"
                for dep in another_results
            )
            state_text = (
                f"Objetivo geral: {task.goal}\n\n"
                f"Etapa {step_number}: {step.get('description', '')}\n"
                f"Critérios de conclusão: {step.get('completion_criteria', [])}\n\n"
                f"Resultado produzido:\n{step_result[:600]}\n\n"
                f"Etapas dependentes:\n{dependents_summary}"
            )

            verdict = self.classifier.verify_integration(state_text)

            if verdict["approved"]:
                console.log(f"Passo {step_number} aprovado na inspeção (Laya).")
                return False

            console.warn(
                f"Laya solicitou uma revisão do passo {step_number} "
                f"(confiança: {verdict.get('answer_confidence', 0.0):.2f})."
            )
            step_to_modify = self.slice_step(task, step_number)
            result = self.execute(task, step_to_modify, ExecutionType.MODIFY)
            return result is not None

        except Exception as error:
            console.error(f"Falha ao inspecionar o passo {step_number}: {error}")
            return False

    # ========================================================================
    # Etapa 8: Relatório Final e Loop Principal (do_task)
    # ========================================================================

    def build_final_report(self, task: Task) -> dict[str, Any]:
        """Consolida o relatório final observável da tarefa."""
        history = self._ensure_history(task)
        nodes_summary = [
            {
                "id": node.id,
                "parent_id": node.parent_id,
                "state": node.state.value,
                "classification": (node.classification or {}).get("choice"),
                "decomposed": not node.is_leaf,
                "verification": node.verification,
                "error": node.error,
            }
            for node in task.step_graph.nodes.values()
        ]

        errors_and_corrections = [
            event
            for event in history.get("events", [])
            if event.get("status") in ("error", "warning")
        ]

        pending = [
            node.id
            for node in task.step_graph.nodes.values()
            if node.state != StepNodeState.COMPLETED
        ]

        report = {
            "task_id": task.id,
            "requested_goal": task.goal,
            "final_state": task.state.value,
            "nodes": nodes_summary,
            "artifacts_affected": list(history.get("artifacts", {}).keys()),
            "errors_and_corrections": errors_and_corrections,
            "criteria_satisfied": len(pending) == 0
            and len(task.step_graph.nodes) > 0,
            "pending_nodes": pending,
        }
        task.final_report = report
        return report

    def do_task(self, task: Task) -> Task:
        """Executa o pipeline completo da tarefa sobre o grafo de StepNodes."""
        if task.state == TaskState.FAILED:
            self.build_final_report(task)
            return task

        if not task.step_graph.root_ids:
            console.error("A tarefa não possui StepNodes planejados.")
            if task.state in (TaskState.READY, TaskState.PLANNING):
                self._transition(task, TaskState.FAILED)
            self.build_final_report(task)
            return task

        if task.state == TaskState.READY:
            self._transition(task, TaskState.RUNNING)

        try:
            # 1. Classificação discriminativa (Laya)
            self.classify_steps(task)

            # 2. Decomposição (Code Breaker -> Composer)
            self.decompose_steps(task)

            # 3. Execução das folhas + Recomposição AST + Verificação em ordem topológica
            ordered_roots = task.step_graph.topological_order(
                task.step_graph.root_ids
            )
            all_ok = True
            for position, root_id in enumerate(ordered_roots, start=1):
                task.current_steps = position
                ok = self._execute_subtree(task, root_id)
                if not ok:
                    all_ok = False
                    break

            # 4. Verificação de integração adicional sobre nós que possuem dependentes
            if all_ok:
                console.warn("Iniciando verificação final de integração..")
                for root_id in ordered_roots:
                    if task.step_graph.get_dependents(root_id):
                        if not self.verify_and_correct_node(
                            task,
                            root_id,
                            run_semantic_check=True,
                        ):
                            all_ok = False
                            break

            if all_ok:
                self._transition(task, TaskState.COMPLETED)
            else:
                self._transition(task, TaskState.FAILED)

        except Exception as error:
            task.error = str(error)
            self.add_context_history(
                task,
                "runtime_failed",
                f"Erro inesperado durante execução da tarefa: {error}",
                status="error",
            )
            if task.state not in (
                TaskState.FAILED,
                TaskState.COMPLETED,
                TaskState.CANCELLED,
            ):
                self._transition(task, TaskState.FAILED)

        self.build_final_report(task)
        return task
