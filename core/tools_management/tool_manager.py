import os
import shlex
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")


class ToolType(Enum):
    """Categorias de ferramentas autorizadas no Atom."""

    CREATE = 1
    READ = 2
    UPDATE = 3
    DELETE = 4
    COMPILE = 5
    EXECUTE = 6
    OTHER = 7


@dataclass
class ToolData:
    """Metadados de uma ferramenta registrada no Registry."""

    id: int
    type: ToolType
    path: str
    desc: str


DEFAULT_LAYA_QUESTIONS: dict[str, Any] = {
    "tool": {
        "type": "choice",
        "instructions": "Qual ferramenta deve atender à solicitação do usuário?",
        "criteria": {
            "create": "Criar arquivos ou diretórios",
            "read": "Ler arquivos ou conteúdos de diretórios",
            "update": "Modificar ou escrever em arquivos existentes",
            "delete": "Excluir arquivos ou diretórios",
            "compile": "Compilar código-fonte ou validar construção do projeto",
            "execute": "Executar programas, binários ou testes",
            "other": "Solicitações que não correspondem a essas ferramentas",
        },
    }
}


DEFAULT_LAYA_VERIFICATION_QUESTIONS: dict[str, Any] = {
    "integration": {
        "type": "choice",
        "instructions": (
            "Avalie se o resultado produzido para a etapa atual atende aos "
            "critérios de conclusão e integra corretamente com as etapas dependentes."
        ),
        "criteria": {
            "approved": (
                "O resultado está consistente com a etapa, atende aos critérios "
                "e funciona em conjunto com os dependentes sem falhas importantes."
            ),
            "needs_revision": (
                "O resultado apresenta erro claro, omissão relevante, conflito de "
                "nomes ou incompatibilidade que exige revisão."
            ),
        },
    }
}


class ToolClassifier:
    """
    Classificador discriminativo de passos usando o modelo Laya.

    Identifica o tipo de operação predominante de um StepNode sem substituir
    o planejamento generativo do Ollama.
    """

    TOOL_TYPE_BY_CHOICE: dict[str, ToolType] = {
        "create": ToolType.CREATE,
        "read": ToolType.READ,
        "update": ToolType.UPDATE,
        "delete": ToolType.DELETE,
        "compile": ToolType.COMPILE,
        "execute": ToolType.EXECUTE,
        "other": ToolType.OTHER,
    }

    def __init__(
        self,
        *,
        device: str = "cpu",
        preload_models: list[str] | None = None,
        test_mode: bool = False,
        router: Any | None = None,
    ) -> None:
        self.device = device
        self.preload_models = (
            preload_models if preload_models is not None else ["multilingual"]
        )
        self.test_mode = test_mode
        self._router = router

    def _ensure_router(self) -> Any:
        """Inicializa o Router do Laya sob demanda."""
        if self._router is not None:
            return self._router

        from laya import Router

        router = Router(device=self.device)
        if self.preload_models:
            router.preload(self.preload_models)
        self._router = router
        return self._router

    def classify(
        self,
        text: str,
        *,
        effects: dict[str, list[str]] | None = None,
        questions: dict[str, Any] | None = None,
        lang: str = "pt-BR",
    ) -> dict[str, Any]:
        """
        Classifica uma descrição de passo retornando escolha, tipo e confiança.
        """
        if not isinstance(text, str) or not text.strip():
            raise ValueError("O texto para classificação não pode ser vazio.")

        if self.test_mode:
            return self._heuristic_classify(text, effects=effects)

        try:
            router = self._ensure_router()
            active_questions = (
                questions if questions is not None else DEFAULT_LAYA_QUESTIONS
            )
            result = router.predict(text, active_questions, lang=lang)
            answer = result["answers"]["tool"]
            choice = str(answer["choice"]).lower()
            tool_type = self.TOOL_TYPE_BY_CHOICE.get(choice, ToolType.OTHER)

            return {
                "choice": choice,
                "tool_type": tool_type.name,
                "probabilities": dict(answer.get("probabilities", {})),
                "answer_confidence": float(answer.get("answer_confidence", 0.0)),
                "confidence": float(answer.get("confidence", 0.0)),
                "model": result.get("routing", {}).get("model", "laya"),
                "fallback": False,
            }
        except Exception as error:
            fallback = self._heuristic_classify(text, effects=effects)
            fallback["fallback_reason"] = str(error)
            return fallback

    def verify_integration(
        self,
        state_text: str,
        *,
        questions: dict[str, Any] | None = None,
        lang: str = "pt-BR",
    ) -> dict[str, Any]:
        """
        Avalia discriminativamente via Laya se uma etapa está íntegra e aprovada
        ou se precisa de revisão frente aos dependentes.
        """
        if not isinstance(state_text, str) or not state_text.strip():
            raise ValueError(
                "O texto de contexto para verificação não pode ser vazio."
            )

        if self.test_mode:
            return {
                "approved": True,
                "choice": "approved",
                "probabilities": {"approved": 1.0, "needs_revision": 0.0},
                "answer_confidence": 1.0,
                "confidence": 1.0,
                "model": "deterministic-fallback",
                "fallback": True,
            }

        try:
            router = self._ensure_router()
            active_questions = (
                questions
                if questions is not None
                else DEFAULT_LAYA_VERIFICATION_QUESTIONS
            )
            result = router.predict(state_text, active_questions, lang=lang)
            answer = result["answers"]["integration"]
            choice = str(answer["choice"]).lower()

            return {
                "approved": choice == "approved",
                "choice": choice,
                "probabilities": dict(answer.get("probabilities", {})),
                "answer_confidence": float(answer.get("answer_confidence", 0.0)),
                "confidence": float(answer.get("confidence", 0.0)),
                "model": result.get("routing", {}).get("model", "laya"),
                "fallback": False,
            }
        except Exception as error:
            return {
                "approved": True,
                "choice": "approved",
                "probabilities": {"approved": 1.0, "needs_revision": 0.0},
                "answer_confidence": 1.0,
                "confidence": 1.0,
                "model": "deterministic-fallback",
                "fallback": True,
                "fallback_reason": str(error),
            }

    def _heuristic_classify(
        self,
        text: str,
        *,
        effects: dict[str, list[str]] | None = None,
    ) -> dict[str, Any]:
        """Classificação determinística usada em test_mode ou fallback offline."""
        if isinstance(effects, dict):
            if effects.get("deletes"):
                choice = "delete"
            elif effects.get("creates"):
                choice = "create"
            elif effects.get("modifies"):
                choice = "update"
            elif effects.get("reads"):
                choice = "read"
            else:
                choice = self._choice_from_keywords(text)
        else:
            choice = self._choice_from_keywords(text)

        tool_type = self.TOOL_TYPE_BY_CHOICE.get(choice, ToolType.OTHER)
        return {
            "choice": choice,
            "tool_type": tool_type.name,
            "probabilities": {choice: 1.0},
            "answer_confidence": 1.0,
            "confidence": 1.0,
            "model": "deterministic-fallback",
            "fallback": True,
        }

    @staticmethod
    def _choice_from_keywords(text: str) -> str:
        lowered = text.lower()
        if any(word in lowered for word in ("excluir", "remover", "deletar", "apagar", "delete")):
            return "delete"
        if any(word in lowered for word in ("compilar", "compile", "javac", "build")):
            return "compile"
        if any(word in lowered for word in ("executar", "rodar", "testar", "run", "execute")):
            return "execute"
        if any(word in lowered for word in ("modificar", "atualizar", "editar", "alterar", "corrigir", "update")):
            return "update"
        if any(word in lowered for word in ("ler", "listar", "inspecionar", "read", "list")):
            return "read"
        if any(word in lowered for word in ("criar", "gerar", "definir", "implementar", "create")):
            return "create"
        return "other"


class ToolRegistry:
    """
    Registro central de ferramentas autorizadas do Atom.

    Segue o formato definido em tool_registry.sample.py e adiciona validação
    básica de caminhos e integração com o workspace.
    """

    def __init__(self, workspace_root: str | Path | None = None) -> None:
        self.workspace_root = (
            Path(workspace_root).resolve()
            if workspace_root is not None
            else Path.cwd().resolve()
        )
        self.registries: list[ToolData] = []
        self._register_default_tools()

    def registry(self, id: int, type: ToolType, path: str, desc: str) -> None:
        """Cadastra uma ferramenta autorizada no registro."""
        if not isinstance(id, int):
            raise ValueError("O id da ferramenta deve ser um inteiro.")
        if not isinstance(type, ToolType):
            raise ValueError("O tipo da ferramenta deve ser ToolType.")
        if any(tool.id == id for tool in self.registries):
            raise ValueError(f"Já existe uma ferramenta registrada com id {id}.")

        self.registries.append(ToolData(id=id, type=type, path=path, desc=desc))

    def _register_default_tools(self) -> None:
        """Registra as ferramentas padrão disponíveis no diretório tools/."""
        self.registry(
            1,
            ToolType.CREATE,
            "tools/create/create_file.sh",
            "Cria um ou mais arquivos (e diretórios pais) com segurança.",
        )
        self.registry(
            2,
            ToolType.CREATE,
            "tools/create/create_directory.sh",
            "Cria um ou mais diretórios recursivamente com mkdir -p.",
        )
        self.registry(
            3,
            ToolType.READ,
            "tools/read/read_archive.sh",
            "Lê o conteúdo completo ou um intervalo de linhas de um arquivo.",
        )
        self.registry(
            4,
            ToolType.READ,
            "tools/read/list_archives.sh",
            "Lista arquivos e diretórios no workspace respeitando profundidade.",
        )
        self.registry(
            5,
            ToolType.DELETE,
            "tools/delete/delete_archive.sh",
            "Remove arquivos regulares ou links simbólicos autorizados.",
        )
        self.registry(
            6,
            ToolType.DELETE,
            "tools/delete/delete_directory.sh",
            "Remove diretórios autorizados dentro do workspace.",
        )
        self.registry(
            7,
            ToolType.UPDATE,
            "tools/update/write_file.sh",
            "Escreve ou sobrescreve conteúdo textual em um arquivo [conteudo, caminho].",
        )
        self.registry(
            8,
            ToolType.UPDATE,
            "tools/update/append_file.sh",
            "Adiciona conteúdo textual ao final de um arquivo [conteudo, caminho].",
        )
        self.registry(
            9,
            ToolType.UPDATE,
            "tools/update/replace_in_file.sh",
            "Substitui um trecho exato dentro de um arquivo [caminho, alvo, novo_texto].",
        )
        self.registry(
            10,
            ToolType.UPDATE,
            "tools/update/rename_archive.sh",
            "Renomeia ou move um arquivo/diretório dentro do workspace [origem, destino].",
        )

    def find(self, tool_id: int) -> ToolData:
        """Localiza uma ferramenta pelo seu identificador inteiro."""
        if not isinstance(tool_id, int):
            raise ValueError("O valor de tool_id era para ser inteiro.")

        for tool in self.registries:
            if tool.id == tool_id:
                return tool

        raise ValueError(f"tool id não foi encontrado para o valor {tool_id}")

    def find_by_type(self, tool_type: ToolType) -> list[ToolData]:
        """Retorna todas as ferramentas compatíveis com o ToolType informado."""
        return [tool for tool in self.registries if tool.type == tool_type]

    def list_tools(self) -> list[dict[str, Any]]:
        """Retorna um resumo serializável das ferramentas disponíveis."""
        return [
            {
                "id": tool.id,
                "type": tool.type.name,
                "path": tool.path,
                "desc": tool.desc,
            }
            for tool in self.registries
        ]

    def validate_workspace_path(self, target_path: str) -> Path:
        """Garante que um caminho alvo permaneça dentro do workspace."""
        if not isinstance(target_path, str) or not target_path.strip():
            raise ValueError("Caminho de arquivo inválido.")

        candidate = Path(target_path)
        resolved = (
            candidate.resolve()
            if candidate.is_absolute()
            else (self.workspace_root / candidate).resolve()
        )

        if (
            resolved != self.workspace_root
            and self.workspace_root not in resolved.parents
        ):
            raise PermissionError(
                f"Caminho fora do workspace autorizado: {target_path}"
            )

        return resolved

    def execute_tool(
        self,
        tool_id: int,
        args: list[str] | None = None,
    ) -> subprocess.CompletedProcess[str] | dict[str, Any] | None:
        """
        Valida argumentos e executa uma ferramenta registrada.
        """
        if not isinstance(tool_id, int):
            raise ValueError("Esperado tipo int para tool_id em execute_tool.")

        tool = self.find(tool_id)
        safe_args = [] if args is None else args

        if not isinstance(safe_args, list):
            raise ValueError(
                "O valor passado para args não corresponde a um tipo esperado na função."
            )

        script_path = Path(tool.path)
        if not script_path.is_absolute():
            script_path = (Path(__file__).resolve().parents[2] / script_path).resolve()

        if not script_path.exists():
            raise FileNotFoundError(
                f"Script da ferramenta não encontrado: {tool.path}"
            )

        self._validate_tool_args(tool, safe_args)

        quoted_args = [shlex.quote(str(arg)) for arg in safe_args]
        command = f"{shlex.quote(str(script_path))} {' '.join(quoted_args)}".strip()

        try:
            return subprocess.run(
                command,
                check=True,
                shell=True,
                cwd=str(self.workspace_root),
                capture_output=True,
                text=True,
                timeout=30,
            )
        except Exception:
            return None

    def _validate_tool_args(self, tool: ToolData, args: list[Any]) -> None:
        """Valida argumentos de caminhos conforme o tipo da ferramenta."""
        if tool.type in (ToolType.CREATE, ToolType.DELETE):
            for arg in args:
                self.validate_workspace_path(str(arg))
        elif tool.type == ToolType.READ:
            if args:
                self.validate_workspace_path(str(args[0]))
        elif tool.type == ToolType.UPDATE:
            if tool.path.endswith(("write_file.sh", "append_file.sh")) and len(args) >= 2:
                self.validate_workspace_path(str(args[1]))
            elif tool.path.endswith("replace_in_file.sh") and args:
                self.validate_workspace_path(str(args[0]))
            elif tool.path.endswith("rename_archive.sh") and len(args) >= 2:
                self.validate_workspace_path(str(args[0]))
                self.validate_workspace_path(str(args[1]))
