import ast
from pathlib import Path
from typing import Any

from core.code_breaker.ast_recomposer import JavaASTParser


class ProjectAnalyzer:
    """
    Subsistema Analisador do ATOM.

    Coleta fatos reais do workspace (arquivos, diretórios e assinaturas
    principais) sem despejar todo o código no contexto do modelo.
    """

    IGNORED_DIRS = {
        ".git",
        ".venv",
        "__pycache__",
        ".cograph",
        "node_modules",
        ".test",
    }

    def __init__(self, workspace_root: str | Path | None = None) -> None:
        self.workspace_root = (
            Path(workspace_root).resolve()
            if workspace_root is not None
            else Path.cwd().resolve()
        )
        self._java_parser = JavaASTParser()

    def inspect(self, *, max_files: int = 80) -> dict[str, Any]:
        """Inspeciona a estrutura do projeto e extrai assinaturas relevantes."""
        if not self.workspace_root.exists():
            return {
                "workspace": str(self.workspace_root),
                "exists": False,
                "directories": [],
                "files": [],
                "signatures": {},
            }

        directories: list[str] = []
        files: list[str] = []
        signatures: dict[str, dict[str, Any]] = {}

        for path in sorted(self.workspace_root.rglob("*")):
            rel_parts = path.relative_to(self.workspace_root).parts
            if any(part in self.IGNORED_DIRS for part in rel_parts):
                continue

            rel_path = str(path.relative_to(self.workspace_root))
            if path.is_dir():
                directories.append(rel_path)
                continue

            if len(files) >= max_files:
                continue

            files.append(rel_path)
            sig = self._extract_file_signature(path)
            if sig is not None:
                signatures[rel_path] = sig

        return {
            "workspace": str(self.workspace_root),
            "exists": True,
            "directories": directories[:max_files],
            "files": files,
            "signatures": signatures,
        }

    def _extract_file_signature(self, path: Path) -> dict[str, Any] | None:
        """Extrai classes, funções e métodos sem incluir implementações."""
        suffix = path.suffix.lower()
        if suffix not in (".py", ".java"):
            return None

        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            return None

        if suffix == ".py":
            try:
                tree = ast.parse(content)
            except SyntaxError:
                return {"language": "python", "syntax_valid": False}

            classes: list[dict[str, Any]] = []
            functions: list[str] = []
            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    methods = [
                        item.name
                        for item in node.body
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                    ]
                    classes.append({"name": node.name, "methods": methods})
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    functions.append(node.name)

            return {
                "language": "python",
                "syntax_valid": True,
                "classes": classes,
                "functions": functions,
            }

        if suffix == ".java":
            try:
                unit = self._java_parser.parse(content)
            except Exception:
                return {"language": "java", "syntax_valid": False}

            types = [
                {
                    "kind": t.kind,
                    "name": t.name,
                    "members_count": len(t.members),
                }
                for t in unit.types
            ]
            return {
                "language": "java",
                "syntax_valid": True,
                "package": unit.package.name if unit.package else None,
                "types": types,
            }

        return None
