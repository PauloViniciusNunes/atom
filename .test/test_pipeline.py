import ast
import json
import tempfile
import unittest
from pathlib import Path

from core.agent.agent import Agent
from core.code_breaker.ast_recomposer import JavaASTParser, Recomposer
from core.models.step_node import StepGraph, StepNode
from core.pipeline.validator import PlanValidator
from core.runtime.runtime import Runtime
from core.state.states import StepNodeState, TaskState
from core.tools_management.tool_manager import ToolClassifier, ToolRegistry


class MockOllamaAgent(Agent):
    """Agente simulado para testes offline sem acionar o Ollama."""

    def __init__(self, responses: list[str]) -> None:
        super().__init__(test_mode=True)
        self._responses = list(responses)
        self.calls: list[list[dict[str, str]]] = []

    def send(self, messages: list[dict[str, str]]) -> str:
        self.calls.append(messages)
        if not self._responses:
            raise AssertionError("Sem respostas simuladas restantes no MockOllamaAgent.")
        return self._responses.pop(0)


class TestAtomPipeline(unittest.TestCase):
    def test_plan_validator_accepts_new_schema(self) -> None:
        plan = {
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

        validator = PlanValidator()
        validated = validator.validate(plan)
        self.assertEqual(len(validated["steps"]), 1)

    def test_java_ast_recomposer_builds_snake_class(self) -> None:
        parent = StepNode(
            id="1",
            plan={"description": "Criar Snake.java"},
            recomposition_contract={
                "artifact": "Snake.java",
                "structure": "class",
                "members": [
                    {"source_node": 1, "role": "attributes"},
                    {"source_node": 2, "role": "methods"},
                    {"source_node": 3, "role": "methods"},
                ],
            },
        )
        c1 = StepNode(
            id="1.1",
            local_id=1,
            parent_id="1",
            plan={"description": "Atributos e construtor"},
            result=(
                "package game;\n"
                "import java.util.List;\n"
                "private int length = 3;\n"
                "private int[] grid = {0, 1};\n"
                "public Snake(int length) {\n"
                "    this.length = length;\n"
                "}\n"
            ),
        )
        c2 = StepNode(
            id="1.2",
            local_id=2,
            parent_id="1",
            plan={"description": "Método move"},
            result=(
                "public class Snake {\n"
                "    public void move() {\n"
                "        String msg = \"{}\";\n"
                "    }\n"
                "}\n"
            ),
        )
        c3 = StepNode(
            id="1.3",
            local_id=3,
            parent_id="1",
            plan={"description": "Método grow"},
            result=(
                "public void grow() {\n"
                "    this.length++;\n"
                "}\n"
            ),
        )

        recomposer = Recomposer()
        output = recomposer.recompose(parent, [c1, c2, c3])

        unit = JavaASTParser().parse(output, expected_type_name="Snake")
        self.assertIsNotNone(unit.package)
        self.assertEqual(unit.package.name, "game")
        self.assertEqual(len(unit.imports), 1)
        self.assertEqual(len(unit.types), 1)
        self.assertEqual(unit.types[0].name, "Snake")
        self.assertIn("void move()", output)
        self.assertIn("void grow()", output)
        self.assertIn("private int length = 3;", output)

    def test_python_ast_recomposer_builds_class(self) -> None:
        parent = StepNode(
            id="1",
            plan={"description": "Criar snake.py"},
            recomposition_contract={
                "artifact": "snake.py",
                "structure": "class",
                "members": [
                    {"source_node": 1, "role": "attributes"},
                    {"source_node": 2, "role": "methods"},
                ],
            },
        )
        c1 = StepNode(
            id="1.1",
            local_id=1,
            parent_id="1",
            plan={"description": "Atributos e __init__"},
            result=(
                "from dataclasses import dataclass\n"
                "default_length: int = 1\n"
                "def __init__(self, length: int = 1):\n"
                "    self.length = length\n"
            ),
        )
        c2 = StepNode(
            id="1.2",
            local_id=2,
            parent_id="1",
            plan={"description": "Método grow"},
            result=(
                "class Snake:\n"
                "    def grow(self) -> int:\n"
                "        self.length += 1\n"
                "        return self.length\n"
            ),
        )

        output = Recomposer().recompose(parent, [c1, c2])
        parsed = ast.parse(output)
        class_defs = [n for n in parsed.body if isinstance(n, ast.ClassDef)]
        self.assertEqual(len(class_defs), 1)
        self.assertEqual(class_defs[0].name, "snake")
        method_names = [
            n.name
            for n in class_defs[0].body
            if isinstance(n, ast.FunctionDef)
        ]
        self.assertEqual(method_names, ["__init__", "grow"])

    def test_full_offline_pipeline_with_decomposition_and_ast_recomposition(self) -> None:
        plan_json = json.dumps(
            {
                "steps": [
                    {
                        "id": 1,
                        "description": "Criar a classe Snake em Snake.java",
                        "objective": "Implementar entidade Snake com atributos e movimentação",
                        "depends_on": [],
                        "contracts": {
                            "preconditions": [],
                            "postconditions": ["Classe Snake definida"],
                            "invariants": ["Comprimento >= 1"],
                        },
                        "effects": {
                            "reads": [],
                            "creates": ["Snake.java"],
                            "modifies": [],
                            "deletes": [],
                        },
                        "completion_criteria": ["Classe Snake válida"],
                        "decomposition": {"is_divisible": False, "subtasks": []},
                    },
                    {
                        "id": 2,
                        "description": "Criar interface FiguraGeometrica",
                        "objective": "Definir interface simples",
                        "depends_on": [1],
                        "contracts": {
                            "preconditions": [],
                            "postconditions": ["Interface declarada"],
                            "invariants": [],
                        },
                        "effects": {
                            "reads": [],
                            "creates": ["FiguraGeometrica.java"],
                            "modifies": [],
                            "deletes": [],
                        },
                        "completion_criteria": ["Interface válida"],
                        "decomposition": {"is_divisible": False, "subtasks": []},
                    },
                ]
            }
        )

        # Ordem de chamadas ao MockOllamaAgent:
        # 1. plan_task
        # 2. judge_decomposition(step 1) -> true
        # 3. _obtain_decomposition_spec(step 1) -> 2 subtarefas + recomposition_contract
        # 4. judge_decomposition(step 1.1) -> false
        # 5. judge_decomposition(step 1.2) -> false
        # 6. judge_decomposition(step 2) -> false
        # 7. execute_node(1.1) -> attributes
        # 8. execute_node(1.2) -> methods
        # 9. execute_node(2) -> FiguraGeometrica.java
        responses = [
            plan_json,
            json.dumps(
                {
                    "requires_decomposition": True,
                    "reason": "A classe possui atributos e métodos independentes.",
                }
            ),
            json.dumps(
                {
                    "subtasks": [
                        {
                            "id": 1,
                            "role": "attributes",
                            "description": "Definir atributos da classe Snake",
                            "objective": "Criar estado interno",
                            "depends_on": [],
                            "contracts": {
                                "preconditions": [],
                                "postconditions": ["Atributo length definido"],
                                "invariants": [],
                            },
                            "effects": {
                                "reads": [],
                                "creates": [],
                                "modifies": [],
                                "deletes": [],
                            },
                            "completion_criteria": ["Atributos declarados"],
                            "decomposition": {"is_divisible": False, "subtasks": []},
                        },
                        {
                            "id": 2,
                            "role": "methods",
                            "description": "Implementar método move em Snake",
                            "objective": "Movimentar a cobra",
                            "depends_on": [1],
                            "contracts": {
                                "preconditions": [],
                                "postconditions": ["Método move declarado"],
                                "invariants": [],
                            },
                            "effects": {
                                "reads": [],
                                "creates": [],
                                "modifies": [],
                                "deletes": [],
                            },
                            "completion_criteria": ["Método move válido"],
                            "decomposition": {"is_divisible": False, "subtasks": []},
                        },
                    ],
                    "recomposition_contract": {
                        "artifact": "Snake.java",
                        "structure": "class",
                        "members": [
                            {"source_node": 1, "role": "attributes"},
                            {"source_node": 2, "role": "methods"},
                        ],
                    },
                }
            ),
            json.dumps({"requires_decomposition": False, "reason": "Folha simples."}),
            json.dumps({"requires_decomposition": False, "reason": "Folha simples."}),
            json.dumps({"requires_decomposition": False, "reason": "Folha simples."}),
            "private int length = 1;",
            "public void move() {\n    this.length += 1;\n}",
            "public interface FiguraGeometrica {\n    double calcularArea();\n}",
        ]

        agent = MockOllamaAgent(responses)
        classifier = ToolClassifier(test_mode=True)
        runtime = Runtime(agent=agent, classifier=classifier, apply_effects=False)

        task = runtime.create_task("Criar Snake.java e FiguraGeometrica.java")
        runtime.inspect_project(task)
        runtime.plan_task(task)
        self.assertEqual(task.state, TaskState.READY)

        runtime.do_task(task)
        self.assertEqual(task.state, TaskState.COMPLETED)

        parent_node = task.step_graph.get_node("1")
        self.assertEqual(parent_node.state, StepNodeState.COMPLETED)
        self.assertFalse(parent_node.is_leaf)
        self.assertIsNotNone(parent_node.recomposition_contract)
        self.assertIn("public class Snake", parent_node.result or "")
        self.assertIn("private int length = 1;", parent_node.result or "")
        self.assertIn("public void move()", parent_node.result or "")
        self.assertTrue(task.final_report["criteria_satisfied"])

    def test_tool_registry_crud_and_update_scripts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = ToolRegistry(workspace_root=root)

            # 1 e 2: create_directory.sh e create_file.sh (com subpasta)
            self.assertIsNotNone(registry.execute_tool(2, ["src/pkg"]))
            self.assertIsNotNone(registry.execute_tool(1, ["src/pkg/Main.java"]))
            self.assertTrue((root / "src/pkg/Main.java").is_file())

            # 7 e 8: write_file.sh e append_file.sh
            self.assertIsNotNone(
                registry.execute_tool(
                    7,
                    ["line1\nline2\n", "src/pkg/Main.java"],
                )
            )
            self.assertIsNotNone(
                registry.execute_tool(8, ["line3\n", "src/pkg/Main.java"])
            )

            # 9: replace_in_file.sh
            self.assertIsNotNone(
                registry.execute_tool(
                    9,
                    ["src/pkg/Main.java", "line2", "line2_edited"],
                )
            )

            # 3 e 4: read_archive.sh (intervalo) e list_archives.sh
            read_res = registry.execute_tool(3, ["src/pkg/Main.java", "2", "3"])
            self.assertIsNotNone(read_res)
            self.assertEqual(read_res.stdout.strip(), "line2_edited\nline3")

            list_res = registry.execute_tool(4, ["src", "3"])
            self.assertIsNotNone(list_res)
            self.assertIn("src/pkg/Main.java", list_res.stdout)

            # 10: rename_archive.sh
            self.assertIsNotNone(
                registry.execute_tool(
                    10,
                    ["src/pkg/Main.java", "src/pkg/App.java"],
                )
            )
            self.assertFalse((root / "src/pkg/Main.java").exists())
            self.assertTrue((root / "src/pkg/App.java").is_file())

            # 5 e 6: delete_archive.sh e delete_directory.sh
            self.assertIsNotNone(registry.execute_tool(5, ["src/pkg/App.java"]))
            self.assertFalse((root / "src/pkg/App.java").exists())
            self.assertIsNotNone(registry.execute_tool(6, ["src"]))
            self.assertFalse((root / "src").exists())

            # Segurança: bloqueia escape do workspace
            with self.assertRaises(PermissionError):
                registry.execute_tool(7, ["x", "../fora.txt"])

    def test_laya_integration_verification_replaces_yn_prompt(self) -> None:
        class FakeLayaRouter:
            def __init__(self) -> None:
                self.calls = 0

            def predict(self, state, questions, lang="pt-BR", **_kwargs):
                self.calls += 1
                if "tool" in questions:
                    return {
                        "answers": {
                            "tool": {
                                "choice": "create",
                                "probabilities": {"create": 0.95},
                                "answer_confidence": 0.95,
                                "confidence": 0.95,
                            }
                        },
                        "routing": {"model": "multilingual"},
                    }

                # Na primeira verificação de integração pede revisão; após correção aprova
                choice = "needs_revision" if "corrigido" not in state else "approved"
                return {
                    "answers": {
                        "integration": {
                            "choice": choice,
                            "probabilities": {
                                "approved": 0.9 if choice == "approved" else 0.2,
                                "needs_revision": 0.1 if choice == "approved" else 0.8,
                            },
                            "answer_confidence": 0.9 if choice == "approved" else 0.8,
                            "confidence": 0.85,
                        }
                    },
                    "routing": {"model": "multilingual"},
                }

        plan_json = json.dumps(
            {
                "steps": [
                    {
                        "id": 1,
                        "description": "Criar módulo base",
                        "objective": "Definir base",
                        "depends_on": [],
                        "contracts": {
                            "preconditions": [],
                            "postconditions": ["Base definida"],
                            "invariants": [],
                        },
                        "effects": {
                            "reads": [],
                            "creates": ["base.txt"],
                            "modifies": [],
                            "deletes": [],
                        },
                        "completion_criteria": ["Arquivo base definido"],
                        "decomposition": {"is_divisible": False, "subtasks": []},
                    },
                    {
                        "id": 2,
                        "description": "Criar módulo consumidor",
                        "objective": "Consumir base",
                        "depends_on": [1],
                        "contracts": {
                            "preconditions": [],
                            "postconditions": ["Consumidor definido"],
                            "invariants": [],
                        },
                        "effects": {
                            "reads": ["base.txt"],
                            "creates": ["app.txt"],
                            "modifies": [],
                            "deletes": [],
                        },
                        "completion_criteria": ["Consumidor definido"],
                        "decomposition": {"is_divisible": False, "subtasks": []},
                    },
                ]
            }
        )

        # Sem nenhuma chamada Y/N ao MockOllamaAgent:
        # 1. plan_task
        # 2. judge_decomposition(1) -> false
        # 3. judge_decomposition(2) -> false
        # 4. execute_node(1) -> inicial (Laya pedirá revisão na etapa final)
        # 5. execute_node(2)
        # 6. execute_node(1, MODIFY) -> corrigido (Laya aprovará)
        responses = [
            plan_json,
            json.dumps({"requires_decomposition": False, "reason": "Simples."}),
            json.dumps({"requires_decomposition": False, "reason": "Simples."}),
            "conteudo inicial",
            "consumidor usa base",
            "conteudo corrigido",
        ]

        agent = MockOllamaAgent(responses)
        fake_router = FakeLayaRouter()
        classifier = ToolClassifier(test_mode=False, router=fake_router)
        runtime = Runtime(agent=agent, classifier=classifier, apply_effects=False)

        task = runtime.create_task("Testar verificação com Laya")
        runtime.inspect_project(task)
        runtime.plan_task(task)
        runtime.do_task(task)

        self.assertEqual(task.state, TaskState.COMPLETED)
        node1 = task.step_graph.get_node("1")
        self.assertEqual(node1.state, StepNodeState.COMPLETED)
        self.assertEqual(node1.result, "conteudo corrigido")
        self.assertTrue(node1.verification["laya_verification"]["approved"])
        self.assertEqual(len(agent.calls), 6)

    def test_runtime_applies_tool_registry_effects_for_dirs_files_and_deletes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tmp").mkdir()
            (root / "tmp/old.txt").write_text("obsoleto", encoding="utf-8")

            plan_json = json.dumps(
                {
                    "steps": [
                        {
                            "id": 1,
                            "description": "Criar estrutura de diretórios",
                            "objective": "Criar pastas css e html",
                            "depends_on": [],
                            "contracts": {
                                "preconditions": [],
                                "postconditions": ["Pastas criadas"],
                                "invariants": [],
                            },
                            "effects": {
                                "reads": [],
                                "creates": ["css/", "html/"],
                                "modifies": [],
                                "deletes": [],
                            },
                            "completion_criteria": ["Pastas criadas"],
                            "decomposition": {"is_divisible": False, "subtasks": []},
                        },
                        {
                            "id": 2,
                            "description": "Criar arquivo html/index.html",
                            "objective": "Gerar HTML inicial",
                            "depends_on": [1],
                            "contracts": {
                                "preconditions": [],
                                "postconditions": ["index.html criado"],
                                "invariants": [],
                            },
                            "effects": {
                                "reads": [],
                                "creates": ["html/index.html"],
                                "modifies": [],
                                "deletes": [],
                            },
                            "completion_criteria": ["Arquivo criado"],
                            "decomposition": {"is_divisible": False, "subtasks": []},
                        },
                        {
                            "id": 3,
                            "description": "Atualizar html/index.html e limpar arquivo antigo",
                            "objective": "Conectar CSS e remover temporário",
                            "depends_on": [2],
                            "contracts": {
                                "preconditions": [],
                                "postconditions": ["HTML atualizado"],
                                "invariants": [],
                            },
                            "effects": {
                                "reads": [],
                                "creates": [],
                                "modifies": ["html/index.html"],
                                "deletes": ["tmp/old.txt"],
                            },
                            "completion_criteria": ["HTML atualizado"],
                            "decomposition": {"is_divisible": False, "subtasks": []},
                        },
                    ]
                }
            )

            responses = [
                plan_json,
                json.dumps({"requires_decomposition": False, "reason": "Simples."}),
                json.dumps({"requires_decomposition": False, "reason": "Simples."}),
                json.dumps({"requires_decomposition": False, "reason": "Simples."}),
                "Diretórios css/ e html/ preparados.",
                "```html\n<html><body>Inicial</body></html>\n```",
                "```html\n<html><head><link rel='stylesheet' href='../css/styles.css'></head><body>Pronto</body></html>\n```",
            ]

            agent = MockOllamaAgent(responses)
            registry = ToolRegistry(workspace_root=root)
            classifier = ToolClassifier(test_mode=True)
            runtime = Runtime(
                agent=agent,
                classifier=classifier,
                registry=registry,
                workspace_root=root,
                apply_effects=True,
            )

            task = runtime.create_task("Criar estrutura web")
            runtime.inspect_project(task)
            runtime.plan_task(task)
            runtime.do_task(task)

            self.assertEqual(task.state, TaskState.COMPLETED)
            self.assertTrue((root / "css").is_dir())
            self.assertTrue((root / "html").is_dir())
            self.assertTrue((root / "html/index.html").is_file())
            self.assertIn(
                "styles.css",
                (root / "html/index.html").read_text(encoding="utf-8"),
            )
            self.assertFalse((root / "tmp/old.txt").exists())


if __name__ == "__main__":
    unittest.main()
