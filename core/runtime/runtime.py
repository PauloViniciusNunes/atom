from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from core.agent.agent import Agent
from core.state.states import TaskState
from core.style.console import Console
from datetime import datetime, timezone
import json

from enum import Enum

class ExecutionType(Enum):
    """Tipo de tarefa a ser feita"""

    CREATE = "create"
    MODIFY = "modify"

console = Console()

def is_int(valor: str) -> bool:
    try:
        int(valor)
        return True
    except ValueError:
        return False

import re

def parse_code(response: str) -> str:
    """Remove as cercas Markdown quando a resposta contém um bloco de código."""

    if not isinstance(response, str) or not response.strip():
        raise ValueError("A resposta está vazia ou não é válida.")

    response = response.strip()

    pattern = re.compile(
        r"^[ \t]*(?P<fence>`{3,})"
        r"[ \t]*(?P<language>[a-zA-Z0-9_+#.-]*)[ \t]*\n"
        r"(?P<code>.*?)"
        r"\n[ \t]*(?P=fence)[ \t]*$",
        re.DOTALL,
    )

    match = pattern.fullmatch(response)

    if match:
        return match.group("code").strip()

    return response

def iterative_union(execution_history: list | dict) -> set:
    if isinstance(execution_history, dict):
        steps = execution_history.get("steps", [])
    elif isinstance(execution_history, (list, tuple, set)):
        steps = execution_history
    else:
        return set()

    depends_on = set()

    for step in steps.values():
        dependencies = step.get("depends_on", [])

        if isinstance(dependencies, (list, tuple, set)):
            depends_on.update(dependencies)
        elif dependencies is not None:
            depends_on.add(dependencies)

    return depends_on

def search_registry(history: dict, key: str, target):
    if not isinstance(history, dict):
        return None

    # Pesquisa nos passos, que são indexados pelo ID.
    if key in ("step_id", "id"):
        steps = history.get("steps", {})

        if isinstance(steps, dict):
            step = steps.get(str(target))

            if isinstance(step, dict):
                return step

    # Pesquisa nos eventos, que são uma lista de registros.
    events = history.get("events", [])

    if isinstance(events, list):
        for element in events:
            if isinstance(element, dict) and element.get(key) == target:
                return element

    return None

def search_depedents(conjunto: dict, step_id: int) -> set[int]:
    dependents = set()
    steps = conjunto.get("steps", {})

    if not isinstance(steps, dict):
        return dependents

    for dependent_id, node in steps.items():
        if not isinstance(node, dict):
            continue

        dependencies = node.get("depends_on", [])

        if not isinstance(dependencies, (list, tuple, set)):
            continue

        if any(str(dependency_id) == str(step_id)
               for dependency_id in dependencies):
            dependents.add(int(dependent_id))

    return dependents

def execution_messages_by_type(type: ExecutionType, context):
    match type:
        case ExecutionType.CREATE:
            return [
                {
                    "role": "system",
                    "content": (
                        "Você é o agente executor do Atom. "
                        "Sua responsabilidade é produzir o resultado solicitado "
                        "na etapa atual, respeitando seus critérios de conclusão. "
                        "Concentre-se exclusivamente nessa etapa. "
                        "Use os resultados das dependências como referência "
                        "e respeite as restrições do objetivo original. "
                        "Não execute nem descreva etapas futuras. "
                        "Não inclua explicações desnecessárias. "
                        "Não afirme que realizou ações externas, salvou arquivos "
                        "ou executou código se isso não ocorreu."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Execute a etapa descrita no contexto abaixo:\n\n"
                        + json.dumps(
                            context,
                            ensure_ascii=False,
                            indent=2,
                        )
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
                        "de uma etapa já executada, considerando o objetivo original "
                        "da tarefa, os critérios de conclusão da etapa e os resultados "
                        "das etapas que dependem dela.\n\n"

                        "REGRAS DE REVISÃO:\n"
                        "1. Identifique inconsistências, omissões, erros técnicos "
                        "e incompatibilidades com os critérios de conclusão.\n"
                        "2. Verifique se o resultado atual é compatível com as "
                        "necessidades das etapas dependentes, preservando suas "
                        "expectativas e interfaces.\n"
                        "3. Diferencie problemas reais de diferenças meramente "
                        "estilísticas ou de escolhas de implementação válidas.\n"
                        "4. Corrija apenas o que for necessário para resolver "
                        "problemas identificados.\n"
                        "5. Preserve todo comportamento, conteúdo e estrutura "
                        "que já estejam corretos e sejam relevantes.\n"
                        "6. Não introduza funcionalidades, requisitos ou "
                        "dependências que não sejam necessários para a tarefa.\n"
                        "7. Não modifique o escopo da etapa nem tente executar "
                        "as etapas dependentes. Use seus resultados apenas como "
                        "referência para garantir compatibilidade.\n"
                        "8. Se houver código, forneça a versão corrigida completa "
                        "do artefato correspondente, preservando o conteúdo válido. "
                        "Não retorne apenas fragmentos ou uma lista de sugestões.\n"
                        "9. Se o resultado atual já estiver correto, devolva-o "
                        "sem alterações desnecessárias.\n"
                        "10. Não afirme que executou testes, criou arquivos, "
                        "salvou alterações ou realizou ações externas que não ocorreram.\n\n"

                        "FORMATO DA RESPOSTA:\n"
                        "Retorne o resultado revisado da etapa, sem introduções, "
                        "relatórios de análise ou explicações desnecessárias. "
                        "Se o resultado for código, preserve a linguagem e o formato "
                        "adequados ao artefato."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Revise o resultado existente da etapa abaixo e corrija "
                        "os problemas encontrados.\n\n"
                        "Considere o resultado anterior como a base da revisão, "
                        "não como algo a ser descartado automaticamente.\n\n"
                        "O contexto contém o objetivo original, os critérios de "
                        "conclusão, o resultado atual e informações sobre etapas "
                        "dependentes. Utilize essas informações em conjunto antes "
                        "de produzir a versão revisada.\n\n"
                        "CONTEXTO DA REVISÃO:\n\n"
                        + json.dumps(
                            context,
                            ensure_ascii=False,
                            indent=2,
                        )
                    ),
                },
            ]
        case _:
            raise ValueError("Resultado de enum inválido para execution_messages_by_type.")

@dataclass
class Task:
    """Representa uma tarefa gerenciada pelo Atom."""

    goal: str
    id: str = field(default_factory=lambda: str(uuid4()))
    state: TaskState = TaskState.CREATED
    plan_proposal: dict | None = None

    total_steps: int | None = None
    current_steps: int | None = None

    task_context: dict | None = None
    execution_history: dict | None = None

    error: str | None = None
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

class Runtime:
    """Coordena o ciclo de vida das tarefas do Atom."""

    def __init__(self, agent: Agent | None = None):
        self.agent = agent if agent is not None else Agent()

    def _transition(self, task: Task, new_state: TaskState) -> None:
        """Valida e aplica uma transição de estado."""

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
                f"Transição inválida: "
                f"{task.state.name} -> {new_state.name}"
            )

        task.state = new_state

    def add_context_history(self, task: Task, event_type: str, summary: str, *, status: str = "info", step_id: int | None = None, details: dict | None = None,) -> None:
        """Registra um acontecimento no histórico de execução da tarefa."""

        if task.execution_history is None:
            task.execution_history = {}

        history = task.execution_history

        history.setdefault("events", [])
        history.setdefault("steps", {})
        history.setdefault("artifacts", {})

        event = {
            "type": event_type,
            "status": status,
            "summary": summary,
            "step_id": step_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        if details is not None:
            event["details"] = details

        history["events"].append(event)

    def build_execution_context(self, task: Task, step: dict) -> dict:
        """Monta o contexto com os resultados das dependências e ancestrais."""

        if not task.plan_proposal:
            raise ValueError("A tarefa ainda não possui um plano.")

        planned_steps = task.plan_proposal.get("steps", [])
        if not isinstance(planned_steps, list):
            raise ValueError("O plano possui uma lista de passos inválida.")

        # Indexa as etapas para localizar suas dependências rapidamente.
        steps_by_id = {
            planned["id"]: planned
            for planned in planned_steps
        }

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
            """Coleta dependências diretas e transitivas em ordem previsível."""

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

                # Primeiro coleta os ancestrais dessa dependência.
                collect_dependencies(dependency_id)

                # Depois adiciona o resultado da própria dependência.
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

                dependencies.append({
                    "step_id": dependency_id,
                    "description": record.get("description"),
                    "result": result,
                })

        collect_dependencies(step_id)

        return {
            "goal": task.goal,
            "task_context": task.task_context or {},
            "current_step": {
                "id": current_step["id"],
                "description": current_step["description"],
                "completion_criteria": current_step["completion_criteria"],
            },
            "dependencies": dependencies,
        }

    def context_by_depedence(self, task: Task, step: dict):
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
                    "completion_criteria", ""
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
                "completion_criteria": step["completion_criteria"],
                "previous_result": current_record.get("result", ""),
            },
            "dependents": dependents,
        }
    def solve_context(self, task: Task, step: dict, type: ExecutionType):
        """Mapper para montar um tipo de contexto."""

        match type:
            case ExecutionType.CREATE:
                return self.build_execution_context(task, step)
            case ExecutionType.MODIFY:
                return self.context_by_depedence(task, step)
        

    def create_task(self, goal: str) -> Task:
        """Cria uma tarefa sem executá-la."""

        if not isinstance(goal, str) or not goal.strip():
            raise ValueError("O objetivo da tarefa não pode ser vazio.")

        return Task(goal=goal.strip())

    def plan_task(self, task: Task) -> Task:
        """Solicita e valida uma proposta estruturada de plano."""

        if task.state not in (TaskState.CREATED, TaskState.BLOCKED):
            raise ValueError(
                f"A tarefa não pode ser planejada no estado "
                f"{task.state.name}."
            )

        self._transition(task, TaskState.PLANNING)

        messages = [
            {
                "role": "system",
                "content": (
                    "Você é o agente de planejamento do Atom. "
                    "Analise o objetivo e divida-o em passos claros, "
                    "ordenados e verificáveis. "
                    "Não afirme que executou ações. "
                    "Não inclua instalações de qualquer tipo. "
                    "Não escreva código, pseudocódigo ou exemplos executáveis. "
                    "Retorne exclusivamente um objeto JSON válido, "
                    "sem Markdown ou texto adicional, neste formato: "
                    '{"steps": [{"id": 1, '
                    '"description": "Descrição do passo", '
                    '"completion_criteria": "Critério verificável", '
                    '"depends_on": []}]}. '
                    "Os IDs devem começar em 1 e ser sequenciais. "
                    "Cada passo deve possuir os campos id, description, "
                    "completion_criteria e depends_on. "
                    "O campo depends_on deve ser uma lista de IDs inteiros "
                    "dos passos dos quais o passo atual depende diretamente. "
                    "Use uma lista vazia quando não houver dependências. "
                    "Inclua somente dependências realmente necessárias, "
                    "sem assumir que todo passo depende do anterior. "
                    "Uma dependência pode apontar para um passo que aparece "
                    "depois no plano, mas não pode apontar para o próprio passo. "
                    "Não crie dependências circulares. "
                    "Inclua pelo menos um passo."
                ),
            },
            {
                "role": "user",
                "content": f"Objetivo da tarefa:\n{task.goal}",
            },
        ]

        try:
            response = self.agent.send(messages)

            if not isinstance(response, str) or not response.strip():
                raise ValueError("O agente retornou um plano vazio ou inválido.")
            print(response)
            plan = json.loads(parse_code(response))

            if not isinstance(plan, dict):
                raise ValueError("O plano deve ser um objeto JSON.")

            steps = plan.get("steps")

            if not isinstance(steps, list) or not steps:
                raise ValueError("O plano deve conter uma lista de passos.")

            # 1. Validar a estrutura e os campos de cada passo.
            for index, step in enumerate(steps, start=1):
                if not isinstance(step, dict):
                    raise ValueError(
                        f"O passo {index} não é um objeto válido."
                    )

                if type(step.get("id")) is not int or step["id"] != index:
                    raise ValueError(
                        f"ID inválido no passo {index}: esperado {index}."
                    )

                for field_name in ("description", "completion_criteria"):
                    value = step.get(field_name)

                    if not isinstance(value, str) or not value.strip():
                        raise ValueError(
                            f"Campo '{field_name}' inválido no passo {index}."
                        )

                if not isinstance(step.get("depends_on"), list):
                    raise ValueError(
                        f"Campo 'depends_on' deve ser uma lista "
                        f"no passo {index}."
                    )

            # 2. Validar as referências entre os passos.
            valid_ids = {step["id"] for step in steps}
            dependencies = {}

            for step in steps:
                step_id = step["id"]
                depends_on = step["depends_on"]

                if len(depends_on) != len(set(
                    dependency_id
                    for dependency_id in depends_on
                    if type(dependency_id) is int
                )) and all(type(dep_id) is int for dep_id in depends_on):
                    raise ValueError(
                        f"O passo {step_id} possui dependências duplicadas."
                    )

                for dependency_id in depends_on:
                    if type(dependency_id) is not int:
                        raise ValueError(
                            f"Dependência inválida no passo {step_id}: "
                            "o ID deve ser um inteiro."
                        )

                    if dependency_id not in valid_ids:
                        raise ValueError(
                            f"O passo {step_id} depende do passo "
                            f"inexistente {dependency_id}."
                        )

                    if dependency_id == step_id:
                        raise ValueError(
                            f"O passo {step_id} não pode depender de si mesmo."
                        )

                dependencies[step_id] = depends_on

            # 3. Detectar ciclos no grafo de dependências.
            visiting = set()
            visited = set()

            def visit(step_id: int) -> None:
                if step_id in visiting:
                    raise ValueError(
                        "O plano possui dependências circulares."
                    )

                if step_id in visited:
                    return

                visiting.add(step_id)

                for dependency_id in dependencies[step_id]:
                    visit(dependency_id)

                visiting.remove(step_id)
                visited.add(step_id)

            for step_id in dependencies:
                visit(step_id)

            # 4. Registrar a proposta validada estruturalmente.
            task.plan_proposal = plan
            task.total_steps = len(steps)
            task.current_steps = 1
            task.error = None

            # Ainda é necessária a validação semântica do plano.
            return task

        except Exception as error:
            task.error = str(error)
            console.error(
                f"Erro ao criar o planejamento inicial: {error}"
            )
            self._transition(task, TaskState.FAILED)
            return task

    # Seleciona o passo atual.
    def slice_step(self, task: Task, step: int) -> dict:
        if task.plan_proposal is None:
            raise ValueError("A tarefa não possui um plano.")

        steps = task.plan_proposal["steps"]

        if not 1 <= step <= len(steps):
            raise ValueError("Número do passo fora do intervalo válido.")

        return steps[step - 1]
    
    # Executa um passo específico
    def execute(self, task: Task, step: dict, type: ExecutionType) -> str | None:
        """Solicita ao agente a execução de um passo do plano."""

        step_id = step["id"]
        current_goal = step["description"]
        completion_criteria = step["completion_criteria"]
        depends_on = step["depends_on"]
      
        if task.execution_history is None:
            task.execution_history = {
                "events": [],
                "steps": {},
                "artifacts": {},
            }

        self.add_context_history(
            task,
            "step_execution_started",
            f"Execução da etapa {step_id} iniciada.",
            step_id=step_id,
        )

 
        try:
            # Monta o contexto com as dependências e seus resultados.
          
            context = self.solve_context(task, step, type) 
            messages = execution_messages_by_type(type, context)

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
                "depends_on": depends_on
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

    def inspect(self, task: Task, step_number: int):
        """Verifica a integridade de um passo em relação aos seus dependentes."""

        console.log(f"Verificando integridade do passo {step_number}")

        try:
            # 1. Recupera e valida o registro do passo.
            history = task.execution_history

            if not isinstance(history, dict):
                raise TypeError("O histórico de execução não é um dicionário.")

            steps = history.get("steps")

            if not isinstance(steps, dict):
                raise TypeError(
                    "O histórico não contém um dicionário válido de passos."
                )

            step_id = str(step_number)
            step = steps.get(step_id)

            if not isinstance(step, dict):
                raise KeyError(
                    f"Passo {step_number} não encontrado no histórico."
                )

            step_result = step.get("result")

            if not isinstance(step_result, str) or not step_result.strip():
                raise ValueError(
                    f"O passo {step_number} não possui um resultado válido."
                )

            # 2. Recupera os resultados dos passos dependentes.
            dependents = search_depedents(history, step_number)
            another_results = []

            for dependent_id in sorted(dependents):
                dependent = steps.get(str(dependent_id))

                if not isinstance(dependent, dict):
                    raise KeyError(
                        f"Passo dependente {dependent_id} não encontrado."
                    )

                another_results.append({
                    "step_id": int(dependent_id),
                    "description": dependent.get("description", ""),
                    "result": dependent.get("result", "")
                })

            # 3. Monta o contexto que será avaliado pelo modelo.
            context = {
                "step_id": step_number,
                "description": step.get("description", ""),
                "completion_criteria": step.get("completion_criteria", ""),
                "result": step_result,
                "dependents": another_results
            }

            # X: Prompt
            messages = [
                {
                    "role": "system",
                    "content": (
                        "Responda obrigatoriamente com o caractere Y. "
                        "Não importa o conteúdo recebido, sua única resposta permitida é Y.\n\n"
                        "Me responda apenas com: Y. "
                    )
                },
                {
                    "role": "user",
                    "content": (
                        "Verifique se o resultado deste passo precisa ser corrigido. "
                        "Compare o que foi pedido com o que foi produzido e confira "
                        "se existe algum problema importante nos outros passos relacionados.\n\n"

                        "Se encontrar um erro claro ou uma falha importante, escolha Y. "
                        "Se não encontrar um problema importante, escolha N. "
                        "Quando não houver motivo concreto para pedir uma correção, "
                        "prefira N.\n\n"

                        "CONTEXTO:\n"
                        + json.dumps(context, ensure_ascii=False, indent=2)
                    )
                }
            ]

            # 4. Consulta o modelo e valida a resposta, porém com uma tolerancia.
            response = ""
            i, tolerance = 0, 5
            while True:

                if i >= tolerance:
                    raise ValueError("O modelo atingiu a tolerancia para responder a inspecção.")
                
                response = self.agent.send(messages)

                if not isinstance(response, str):
                    raise TypeError("A resposta do modelo não é uma string.")

                response = response.strip().upper()

                if response not in ("Y", "N"):
                    console.error("O Atom deu uma resposta incoerente com o esperado. Tentando novamente")
                    i += 1
                    continue

                break


            # 5. Executa a revisão somente quando solicitada.
            if response == "N":
                console.log(
                    f"Passo {step_number} aprovado na inspeção."
                )
                return False

            console.warn(
                f"Atom solicitou uma revisão do passo {step_number}."
            )

            step_to_modify = self.slice_step(task, step_number)

            if step_to_modify is None:
                raise ValueError(
                    f"Não foi possível preparar o passo {step_number} "
                    "para modificação."
                )

            result = self.execute(
                task,
                step_to_modify,
                ExecutionType.MODIFY
            )

            if result is None:
                console.warn(
                    f"A revisão do passo {step_number} não retornou resultado."
                )
                return False

            print(result)
            return True

        except Exception as error:
            console.error(
                f"Falha ao inspecionar o passo {step_number}: {error}"
            )
            return False

    # Loop de execução da tarefa
    def do_task(self, task):
        # Se não tiver passos válidos não consegue fazer
        if task.total_steps is None or task.current_steps is None:
            console.error("Total de passos ou passos atuais inválidos.")
            return
        
        # Ainda não válida, apenas vai fazendo todos os passos
        while task.current_steps <= task.total_steps:
            current_goal: str = self.slice_step(task, task.current_steps)
            result: str = self.execute(task, current_goal, ExecutionType.CREATE)
            console.log("Executado")
            task.current_steps = task.current_steps + 1

        console.warn("Inspecção iniciada")
        # === INSPECÇÃO

        u = iterative_union(task.execution_history)
        for node in u:
            self.inspect(task, node)

        # 3. Itera sob D - U
            # Corrige ou OK
