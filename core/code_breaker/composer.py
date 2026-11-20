import json
from typing import Any

from core.agent.agent import Agent
from core.code_breaker.ast_recomposer import strip_markdown_fences
from core.models.step_node import StepGraph, StepNode
from core.state.states import StepNodeState
from core.tools_management.tool_manager import ToolClassifier


class Composer:
    """
    Componente do Code Breaker responsável por julgar e decompor StepNodes
    complexos em unidades menores e registrar o contrato de recomposição no pai.
    """

    def __init__(
        self,
        agent: Agent,
        classifier: ToolClassifier | None = None,
        *,
        max_depth: int = 2,
    ) -> None:
        self.agent = agent
        self.classifier = classifier
        self.max_depth = max_depth

    def judge_decomposition(self, node: StepNode) -> dict[str, Any]:
        """
        Consulta o modelo generativo para decidir se o StepNode deve ser dividido.

        Retorna um dicionário no formato:
        {"requires_decomposition": bool, "reason": str}.
        """
        decomposition_hint = node.plan.get("decomposition", {})
        if (
            isinstance(decomposition_hint, dict)
            and decomposition_hint.get("is_divisible") is True
            and isinstance(decomposition_hint.get("subtasks"), list)
            and len(decomposition_hint["subtasks"]) > 0
        ):
            decision = {
                "requires_decomposition": True,
                "reason": "O plano inicial já indicou subtarefas divisíveis para este passo.",
            }
            node.decomposition_decision = decision
            return decision

        messages = [
            {
                "role": "system",
                "content": (
                    "Você é o componente Composer do Code Breaker no ATOM. "
                    "Sua tarefa é julgar se o StepNode informado deve ser dividido "
                    "em StepNodes filhos menores ou executado diretamente.\n"
                    "Retorne EXCLUSIVAMENTE um JSON válido, sem Markdown ou texto extra, "
                    "exatamente neste formato:\n"
                    '{"requires_decomposition": true, "reason": "Justificativa objetiva."}\n'
                    "ou\n"
                    '{"requires_decomposition": false, "reason": "Justificativa objetiva."}'
                ),
            },
            {
                "role": "user",
                "content": (
                    "Avalie se a etapa abaixo precisa de decomposição:\n\n"
                    + json.dumps(
                        {
                            "id": node.id,
                            "plan": node.plan,
                            "classification": node.classification,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                ),
            },
        ]

        raw_response = self.agent.send(messages)
        decision = json.loads(strip_markdown_fences(raw_response))

        if not isinstance(decision, dict):
            raise ValueError("Decisão de decomposição deve ser um objeto JSON.")

        requires = decision.get("requires_decomposition")
        reason = decision.get("reason")

        if type(requires) is not bool:
            raise ValueError(
                "Campo 'requires_decomposition' deve ser booleano."
            )
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("Campo 'reason' deve ser uma string não vazia.")

        normalized = {
            "requires_decomposition": requires,
            "reason": reason.strip(),
        }
        node.decomposition_decision = normalized
        return normalized

    def decompose_node(
        self,
        graph: StepGraph,
        node: StepNode,
        *,
        goal: str,
    ) -> list[StepNode]:
        """
        Decompõe um StepNode caso necessário, criando os filhos no StepGraph e
        armazenando o contrato de recomposição no StepNode pai.
        """
        if node.depth >= self.max_depth:
            node.decomposition_decision = {
                "requires_decomposition": False,
                "reason": f"Profundidade máxima de decomposição ({self.max_depth}) atingida.",
            }
            return []

        graph.update_state(node.id, StepNodeState.DECOMPOSING)
        decision = self.judge_decomposition(node)

        if not decision["requires_decomposition"]:
            graph.update_state(node.id, StepNodeState.READY)
            return []

        decomposition_data = self._obtain_decomposition_spec(node, goal=goal)
        subtasks = decomposition_data["subtasks"]
        contract = decomposition_data["recomposition_contract"]

        self._validate_subtasks(subtasks, contract)

        local_to_global: dict[int, str] = {}
        for sub in subtasks:
            local_id = sub["id"]
            local_to_global[local_id] = f"{node.id}.{local_id}"

        created_children: list[StepNode] = []
        for sub in subtasks:
            local_id = sub["id"]
            global_id = local_to_global[local_id]
            sibling_deps = [
                local_to_global[dep]
                for dep in sub.get("depends_on", [])
                if dep in local_to_global
            ]

            child_node = StepNode(
                id=global_id,
                local_id=local_id,
                parent_id=node.id,
                depends_on=sibling_deps,
                role=sub.get("role"),
                plan={
                    "id": local_id,
                    "description": sub["description"],
                    "objective": sub.get("objective", sub["description"]),
                    "depends_on": sub.get("depends_on", []),
                    "contracts": sub.get(
                        "contracts",
                        {
                            "preconditions": [],
                            "postconditions": [],
                            "invariants": [],
                        },
                    ),
                    "effects": sub.get(
                        "effects",
                        {
                            "reads": [],
                            "creates": [],
                            "modifies": [],
                            "deletes": [],
                        },
                    ),
                    "completion_criteria": sub.get(
                        "completion_criteria",
                        ["Subtarefa concluída de forma consistente com o pai"],
                    ),
                    "decomposition": sub.get(
                        "decomposition",
                        {"is_divisible": False, "subtasks": []},
                    ),
                },
            )

            if self.classifier is not None:
                child_node.classification = self.classifier.classify(
                    child_node.description,
                    effects=child_node.effects,
                )
                child_node.state = StepNodeState.CLASSIFIED

            graph.add_node(child_node)
            created_children.append(child_node)

        node.recomposition_contract = contract
        node.plan.setdefault("decomposition", {})
        node.plan["decomposition"]["is_divisible"] = True
        node.plan["decomposition"]["subtasks"] = subtasks
        graph.update_state(node.id, StepNodeState.READY)

        # Decomposição recursiva opcional nos filhos criados
        for child in created_children:
            if child.depth < self.max_depth:
                self.decompose_node(graph, child, goal=goal)
            else:
                graph.update_state(child.id, StepNodeState.READY)

        return created_children

    def _obtain_decomposition_spec(
        self,
        node: StepNode,
        *,
        goal: str,
    ) -> dict[str, Any]:
        """Obtém do plano existente ou do modelo as subtarefas e o contrato."""
        hint = node.plan.get("decomposition", {})
        if (
            isinstance(hint, dict)
            and isinstance(hint.get("subtasks"), list)
            and hint["subtasks"]
            and isinstance(hint.get("recomposition_contract"), dict)
        ):
            return {
                "subtasks": hint["subtasks"],
                "recomposition_contract": hint["recomposition_contract"],
            }

        messages = [
            {
                "role": "system",
                "content": (
                    "Você é o Composer do Code Breaker no ATOM. "
                    "Decomponha o StepNode em subtarefas menores e gere o "
                    "recomposition_contract correspondente.\n"
                    "Retorne EXCLUSIVAMENTE um objeto JSON válido neste formato:\n"
                    "{\n"
                    '  "subtasks": [\n'
                    "    {\n"
                    '      "id": 1,\n'
                    '      "role": "attributes | constructor | methods | imports | body",\n'
                    '      "description": "Descrição clara da subtarefa",\n'
                    '      "objective": "Objetivo da subtarefa",\n'
                    '      "depends_on": [],\n'
                    '      "contracts": {"preconditions": [], "postconditions": [], "invariants": []},\n'
                    '      "effects": {"reads": [], "creates": [], "modifies": [], "deletes": []},\n'
                    '      "completion_criteria": ["Critério verificável"],\n'
                    '      "decomposition": {"is_divisible": false, "subtasks": []}\n'
                    "    }\n"
                    "  ],\n"
                    '  "recomposition_contract": {\n'
                    '    "artifact": "NomeDoArquivo.java",\n'
                    '    "structure": "class",\n'
                    '    "members": [\n'
                    '      {"source_node": 1, "role": "attributes"}\n'
                    "    ]\n"
                    "  }\n"
                    "}\n"
                    "Os IDs das subtarefas devem ser inteiros sequenciais iniciando em 1 "
                    "e cada source_node em members deve corresponder ao id da subtarefa."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Objetivo geral: {goal}\n\n"
                    "StepNode a decompor:\n"
                    + json.dumps(node.plan, ensure_ascii=False, indent=2)
                ),
            },
        ]

        raw_response = self.agent.send(messages)
        payload = json.loads(strip_markdown_fences(raw_response))

        if not isinstance(payload, dict):
            raise ValueError("Especificação de decomposição deve ser JSON objeto.")

        return payload

    @staticmethod
    def _validate_subtasks(
        subtasks: Any,
        contract: Any,
    ) -> None:
        if not isinstance(subtasks, list) or not subtasks:
            raise ValueError("Decomposição exige lista não vazia de subtarefas.")

        valid_ids: set[int] = set()
        deps: dict[int, list[int]] = {}

        for index, sub in enumerate(subtasks, start=1):
            if not isinstance(sub, dict):
                raise ValueError(f"Subtarefa {index} inválida.")
            if type(sub.get("id")) is not int or sub["id"] != index:
                raise ValueError(
                    f"Subtarefa {index} deve possuir id sequencial {index}."
                )
            desc = sub.get("description")
            if not isinstance(desc, str) or not desc.strip():
                raise ValueError(
                    f"Subtarefa {index} deve possuir description válida."
                )
            sub_deps = sub.get("depends_on", [])
            if not isinstance(sub_deps, list) or not all(
                type(d) is int for d in sub_deps
            ):
                raise ValueError(
                    f"Subtarefa {index} possui depends_on inválido."
                )
            valid_ids.add(index)
            deps[index] = sub_deps

        for sid, dep_list in deps.items():
            for dep in dep_list:
                if dep not in valid_ids or dep == sid:
                    raise ValueError(
                        f"Dependência inválida {dep} na subtarefa {sid}."
                    )

        # Detecta ciclos entre subtarefas
        visiting: set[int] = set()
        visited: set[int] = set()

        def visit(cur: int) -> None:
            if cur in visiting:
                raise ValueError("Subtarefas possuem dependências circulares.")
            if cur in visited:
                return
            visiting.add(cur)
            for dep in deps[cur]:
                visit(dep)
            visiting.remove(cur)
            visited.add(cur)

        for sid in valid_ids:
            visit(sid)

        if not isinstance(contract, dict):
            raise ValueError("recomposition_contract deve ser um objeto.")
        if not isinstance(contract.get("artifact"), str) or not contract["artifact"].strip():
            raise ValueError("recomposition_contract exige 'artifact' válido.")
        if not isinstance(contract.get("structure"), str) or not contract["structure"].strip():
            raise ValueError("recomposition_contract exige 'structure' válido.")

        members = contract.get("members")
        if not isinstance(members, list) or not members:
            raise ValueError("recomposition_contract exige 'members' não vazio.")

        for member in members:
            if not isinstance(member, dict):
                raise ValueError("Entrada inválida em 'members'.")
            src = member.get("source_node")
            if src not in valid_ids:
                raise ValueError(
                    f"source_node '{src}' no contrato não existe nas subtarefas."
                )
            if not isinstance(member.get("role"), str) or not member["role"].strip():
                raise ValueError("Cada membro exige 'role' válido.")
