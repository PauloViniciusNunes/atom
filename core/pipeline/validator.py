import ast
from pathlib import Path
from typing import Any

from core.agent.agent import Agent
from core.code_breaker.ast_recomposer import (
    JavaASTParser,
    strip_markdown_fences,
)
from core.models.step_node import StepGraph, StepNode
from core.tools_management.tool_manager import ToolClassifier, ToolRegistry


class PlanValidator:
    """
    Subsistema Validador de planos do ATOM.

    Verifica estrutura, contratos, efeitos, segurança de caminhos,
    compatibilidade com o Registry e ausência de ciclos de dependência.
    """

    REQUIRED_CONTRACT_KEYS = ("preconditions", "postconditions", "invariants")
    REQUIRED_EFFECT_KEYS = ("reads", "creates", "modifies", "deletes")

    def __init__(self, registry: ToolRegistry | None = None) -> None:
        self.registry = registry

    def validate(self, plan: Any) -> dict[str, Any]:
        """Valida integralmente a proposta de plano retornada pelo planejador."""
        if not isinstance(plan, dict):
            raise ValueError("O plano deve ser um objeto JSON.")

        steps = plan.get("steps")
        if not isinstance(steps, list) or not steps:
            raise ValueError("O plano deve conter uma lista não vazia de passos.")

        # 1. Validar campos estruturais, contratos, efeitos e decomposição
        for index, step in enumerate(steps, start=1):
            if not isinstance(step, dict):
                raise ValueError(f"O passo {index} não é um objeto válido.")

            if type(step.get("id")) is not int or step["id"] != index:
                raise ValueError(
                    f"ID inválido no passo {index}: esperado {index}."
                )

            for text_field in ("description", "objective"):
                value = step.get(text_field)
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(
                        f"Campo '{text_field}' inválido no passo {index}."
                    )

            depends_on = step.get("depends_on")
            if not isinstance(depends_on, list):
                raise ValueError(
                    f"Campo 'depends_on' deve ser uma lista no passo {index}."
                )

            self._validate_contracts(step.get("contracts"), index)
            self._validate_effects(step.get("effects"), index)
            self._validate_completion_criteria(
                step.get("completion_criteria"),
                index,
            )
            self._validate_decomposition(step.get("decomposition"), index)

        # 2. Validar referências entre passos
        valid_ids = {step["id"] for step in steps}
        dependencies: dict[int, list[int]] = {}

        for step in steps:
            step_id = step["id"]
            depends_on = step["depends_on"]

            if any(type(dep_id) is not int for dep_id in depends_on):
                raise ValueError(
                    f"Dependência inválida no passo {step_id}: o ID deve ser um inteiro."
                )

            if len(depends_on) != len(set(depends_on)):
                raise ValueError(
                    f"O passo {step_id} possui dependências duplicadas."
                )

            for dependency_id in depends_on:
                if dependency_id not in valid_ids:
                    raise ValueError(
                        f"O passo {step_id} depende do passo inexistente {dependency_id}."
                    )
                if dependency_id == step_id:
                    raise ValueError(
                        f"O passo {step_id} não pode depender de si mesmo."
                    )

            dependencies[step_id] = depends_on

        # 3. Detectar ciclos no grafo de dependências
        visiting: set[int] = set()
        visited: set[int] = set()

        def visit(step_id: int) -> None:
            if step_id in visiting:
                raise ValueError("O plano possui dependências circulares.")
            if step_id in visited:
                return

            visiting.add(step_id)
            for dependency_id in dependencies[step_id]:
                visit(dependency_id)
            visiting.remove(step_id)
            visited.add(step_id)

        for step_id in dependencies:
            visit(step_id)

        return plan

    def _validate_contracts(self, contracts: Any, index: int) -> None:
        if not isinstance(contracts, dict):
            raise ValueError(
                f"Campo 'contracts' deve ser um objeto no passo {index}."
            )
        for key in self.REQUIRED_CONTRACT_KEYS:
            value = contracts.get(key)
            if not isinstance(value, list) or not all(
                isinstance(item, str) for item in value
            ):
                raise ValueError(
                    f"Campo 'contracts.{key}' inválido no passo {index}."
                )

    def _validate_effects(self, effects: Any, index: int) -> None:
        if not isinstance(effects, dict):
            raise ValueError(
                f"Campo 'effects' deve ser um objeto no passo {index}."
            )
        for key in self.REQUIRED_EFFECT_KEYS:
            value = effects.get(key)
            if not isinstance(value, list) or not all(
                isinstance(item, str) and item.strip() for item in value
            ):
                raise ValueError(
                    f"Campo 'effects.{key}' inválido no passo {index}."
                )
            for target_path in value:
                self._validate_safe_path(target_path, index)

    def _validate_safe_path(self, target_path: str, index: int) -> None:
        if self.registry is not None:
            try:
                self.registry.validate_workspace_path(target_path)
            except PermissionError as error:
                raise ValueError(
                    f"Violação de permissão de caminho no passo {index}: {error}"
                ) from error
            return

        candidate = Path(target_path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError(
                f"Caminho inseguro '{target_path}' nos efeitos do passo {index}."
            )

    @staticmethod
    def _validate_completion_criteria(criteria: Any, index: int) -> None:
        if (
            not isinstance(criteria, list)
            or not criteria
            or not all(isinstance(item, str) and item.strip() for item in criteria)
        ):
            raise ValueError(
                f"Campo 'completion_criteria' deve ser uma lista não vazia de strings no passo {index}."
            )

    @staticmethod
    def _validate_decomposition(decomposition: Any, index: int) -> None:
        if not isinstance(decomposition, dict):
            raise ValueError(
                f"Campo 'decomposition' deve ser um objeto no passo {index}."
            )
        if type(decomposition.get("is_divisible")) is not bool:
            raise ValueError(
                f"Campo 'decomposition.is_divisible' deve ser booleano no passo {index}."
            )
        if not isinstance(decomposition.get("subtasks"), list):
            raise ValueError(
                f"Campo 'decomposition.subtasks' deve ser uma lista no passo {index}."
            )


class ResultVerifier:
    """
    Subsistema Verificador do ATOM.

    Executa verificações determinísticas (sintaxe AST, estrutura e contratos)
    e validação integrativa/semântica discriminativa via Laya.
    """

    def __init__(
        self,
        agent: Agent,
        classifier: ToolClassifier | None = None,
    ) -> None:
        self.agent = agent
        self.classifier = (
            classifier
            if classifier is not None
            else ToolClassifier(test_mode=agent.test_mode)
        )
        self._java_parser = JavaASTParser()

    def verify_node(
        self,
        graph: StepGraph,
        node: StepNode,
        *,
        goal: str,
        plan_proposal: dict[str, Any] | None = None,
        run_semantic_check: bool = True,
    ) -> dict[str, Any]:
        """
        Verifica um StepNode (folha ou pai recomposto) em múltiplos níveis.
        """
        checks: dict[str, Any] = {
            "non_empty_result": False,
            "syntax_valid": True,
            "recomposition_valid": True,
            "integration_approved": True,
            "laya_verification": None,
            "issues": [],
        }

        if not isinstance(node.result, str) or not node.result.strip():
            checks["issues"].append(
                f"StepNode '{node.id}' não possui resultado textual válido."
            )
            node.verification = {**checks, "passed": False}
            return node.verification

        checks["non_empty_result"] = True

        # 1. Verificação sintática / estrutural determinística
        artifact_name = self._infer_artifact_name(node)
        syntax_ok, syntax_issue = self._check_syntax(node.result, artifact_name)
        checks["syntax_valid"] = syntax_ok
        if not syntax_ok and syntax_issue:
            checks["issues"].append(syntax_issue)

        # 2. Verificação contratual de recomposição para nós com filhos
        if not node.is_leaf:
            recomp_ok, recomp_issue = self._check_recomposition_contract(
                graph, node
            )
            checks["recomposition_valid"] = recomp_ok
            if not recomp_ok and recomp_issue:
                checks["issues"].append(recomp_issue)

        # 3. Verificação discriminativa de integração via Laya
        dependents = graph.get_dependents(node.id)
        needs_integration_review = (
            run_semantic_check
            and (bool(dependents) or not node.is_leaf)
        )

        if needs_integration_review:
            approved, reason, laya_details = self._check_integration_with_laya(
                graph,
                node,
                goal=goal,
            )
            checks["integration_approved"] = approved
            checks["laya_verification"] = laya_details
            if not approved and reason:
                checks["issues"].append(reason)

        passed = (
            checks["non_empty_result"]
            and checks["syntax_valid"]
            and checks["recomposition_valid"]
            and checks["integration_approved"]
        )
        node.verification = {**checks, "passed": passed}
        return node.verification

    @staticmethod
    def _infer_artifact_name(node: StepNode) -> str:
        if isinstance(node.recomposition_contract, dict):
            artifact = node.recomposition_contract.get("artifact")
            if isinstance(artifact, str) and artifact.strip():
                return artifact.strip()

        effects = node.effects
        for key in ("creates", "modifies"):
            items = effects.get(key, [])
            if items:
                return str(items[0])

        return ""

    def _check_syntax(
        self,
        result: str,
        artifact_name: str,
    ) -> tuple[bool, str | None]:
        cleaned = strip_markdown_fences(result)
        lowered = artifact_name.lower()

        if lowered.endswith(".py"):
            try:
                ast.parse(cleaned)
                return True, None
            except SyntaxError as error:
                return False, f"Erro de sintaxe Python em '{artifact_name}': {error}"

        if lowered.endswith(".java"):
            try:
                unit = self._java_parser.parse(
                    cleaned,
                    expected_type_name=Path(artifact_name).stem,
                )
                if not unit.types and not unit.orphan_members:
                    return False, f"Nenhuma estrutura Java válida encontrada em '{artifact_name}'."
                return True, None
            except Exception as error:
                return False, f"Erro estrutural Java em '{artifact_name}': {error}"

        return True, None

    @staticmethod
    def _check_recomposition_contract(
        graph: StepGraph,
        parent: StepNode,
    ) -> tuple[bool, str | None]:
        contract = parent.recomposition_contract
        if not isinstance(contract, dict):
            return False, (
                f"StepNode pai '{parent.id}' possui filhos, mas não possui recomposition_contract."
            )

        children = graph.get_children(parent.id)
        if not children:
            return False, f"StepNode pai '{parent.id}' sem filhos registrados."

        for child in children:
            if not isinstance(child.result, str) or not child.result.strip():
                return False, (
                    f"Filho '{child.id}' de '{parent.id}' não possui resultado."
                )

        return True, None

    def _check_integration_with_laya(
        self,
        graph: StepGraph,
        node: StepNode,
        *,
        goal: str,
    ) -> tuple[bool, str | None, dict[str, Any]]:
        """Usa o modelo discriminativo Laya para avaliar a integração do StepNode."""
        dependents_summary = [
            f"- Passo {dep.id} ({dep.description}): {(dep.result or '')[:220]}"
            for dep in graph.get_dependents(node.id)
            if dep.result
        ]
        children_summary = [
            f"- Filho {child.id} [{child.role or 'member'}]: {child.description}"
            for child in graph.get_children(node.id)
        ]

        sections = [
            f"Objetivo geral: {goal}",
            f"Etapa {node.id}: {node.description}",
            f"Objetivo da etapa: {node.objective}",
            f"Critérios de conclusão: {', '.join(node.completion_criteria)}",
            f"Resultado produzido:\n{(node.result or '')[:600]}",
        ]
        if children_summary:
            sections.append("Filhos recompostos:\n" + "\n".join(children_summary))
        if dependents_summary:
            sections.append("Etapas dependentes:\n" + "\n".join(dependents_summary))

        state_text = "\n\n".join(sections)
        verdict = self.classifier.verify_integration(state_text)

        if verdict["approved"]:
            return True, None, verdict

        confidence = verdict.get("answer_confidence", 0.0)
        return (
            False,
            f"Laya solicitou revisão de integração para StepNode '{node.id}' (confiança: {confidence:.2f}).",
            verdict,
        )
