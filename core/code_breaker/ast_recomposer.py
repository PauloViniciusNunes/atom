import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.models.step_node import StepNode


def strip_markdown_fences(response: str) -> str:
    """Remove cercas Markdown caso a saída do modelo venha em bloco de código."""
    if not isinstance(response, str) or not response.strip():
        raise ValueError("A resposta está vazia ou não é válida.")

    cleaned = response.strip()
    pattern = re.compile(
        r"^[ \t]*(?P<fence>`{3,})"
        r"[ \t]*(?P<language>[a-zA-Z0-9_+#.-]*)[ \t]*\n"
        r"(?P<code>.*?)"
        r"\n[ \t]*(?P=fence)[ \t]*$",
        re.DOTALL,
    )
    match = pattern.fullmatch(cleaned)
    if match:
        return match.group("code").strip()
    return cleaned


# ============================================================================
# AST Estrutural para Java (Lexer + Parser + Recomposer)
# ============================================================================


@dataclass
class JavaToken:
    """Token léxico para análise estrutural de código Java."""

    kind: str  # COMMENT, STRING, CHAR, ANNOTATION, LBRACE, RBRACE, LPAREN, RPAREN, SEMI, WORD, SYMBOL
    value: str
    start: int
    end: int


class JavaLexer:
    """Tokenizador léxico Java preservando comentários, strings e anotações."""

    def tokenize(self, source: str) -> list[JavaToken]:
        tokens: list[JavaToken] = []
        n = len(source)
        i = 0

        while i < n:
            ch = source[i]

            if ch.isspace():
                i += 1
                continue

            # Comentário de linha
            if source.startswith("//", i):
                end = source.find("\n", i)
                end = n if end == -1 else end
                tokens.append(JavaToken("COMMENT", source[i:end], i, end))
                i = end
                continue

            # Comentário de bloco / Javadoc
            if source.startswith("/*", i):
                end = source.find("*/", i + 2)
                end = n if end == -1 else end + 2
                tokens.append(JavaToken("COMMENT", source[i:end], i, end))
                i = end
                continue

            # String literal
            if ch == '"':
                j = i + 1
                while j < n:
                    if source[j] == "\\":
                        j += 2
                        continue
                    if source[j] == '"':
                        j += 1
                        break
                    j += 1
                tokens.append(JavaToken("STRING", source[i:j], i, j))
                i = j
                continue

            # Char literal
            if ch == "'":
                j = i + 1
                while j < n:
                    if source[j] == "\\":
                        j += 2
                        continue
                    if source[j] == "'":
                        j += 1
                        break
                    j += 1
                tokens.append(JavaToken("CHAR", source[i:j], i, j))
                i = j
                continue

            # Anotação @Nome ou @Nome(...)
            if ch == "@":
                j = i + 1
                while j < n and (source[j].isalnum() or source[j] in "_$."):
                    j += 1
                while j < n and source[j].isspace():
                    j += 1
                if j < n and source[j] == "(":
                    depth = 1
                    j += 1
                    while j < n and depth > 0:
                        if source[j] in ('"', "'"):
                            quote = source[j]
                            j += 1
                            while j < n:
                                if source[j] == "\\":
                                    j += 2
                                    continue
                                if source[j] == quote:
                                    j += 1
                                    break
                                j += 1
                            continue
                        if source[j] == "(":
                            depth += 1
                        elif source[j] == ")":
                            depth -= 1
                        j += 1
                tokens.append(
                    JavaToken("ANNOTATION", source[i:j].strip(), i, j)
                )
                i = j
                continue

            single_map = {
                "{": "LBRACE",
                "}": "RBRACE",
                "(": "LPAREN",
                ")": "RPAREN",
                ";": "SEMI",
            }
            if ch in single_map:
                tokens.append(JavaToken(single_map[ch], ch, i, i + 1))
                i += 1
                continue

            if ch.isalpha() or ch in "_$":
                j = i + 1
                while j < n and (source[j].isalnum() or source[j] in "_$"):
                    j += 1
                tokens.append(JavaToken("WORD", source[i:j], i, j))
                i = j
                continue

            tokens.append(JavaToken("SYMBOL", ch, i, i + 1))
            i += 1

        return tokens


@dataclass
class JavaASTNode:
    """Nó base da AST estrutural Java."""

    leading_comments: list[str] = field(default_factory=list)
    annotations: list[str] = field(default_factory=list)


@dataclass
class PackageNode(JavaASTNode):
    name: str = ""
    raw: str = ""


@dataclass
class ImportNode(JavaASTNode):
    path: str = ""
    is_static: bool = False
    raw: str = ""


@dataclass
class FieldNode(JavaASTNode):
    name: str = ""
    raw: str = ""


@dataclass
class InitializerNode(JavaASTNode):
    is_static: bool = False
    raw: str = ""


@dataclass
class ConstructorNode(JavaASTNode):
    name: str = ""
    signature: str = ""
    raw: str = ""


@dataclass
class MethodNode(JavaASTNode):
    name: str = ""
    signature: str = ""
    raw: str = ""
    is_abstract: bool = False


@dataclass
class TypeDeclNode(JavaASTNode):
    kind: str = "class"  # class | interface | enum | record
    name: str = ""
    header: str = ""
    members: list[JavaASTNode] = field(default_factory=list)


@dataclass
class CompilationUnitNode:
    package: PackageNode | None = None
    imports: list[ImportNode] = field(default_factory=list)
    types: list[TypeDeclNode] = field(default_factory=list)
    orphan_members: list[JavaASTNode] = field(default_factory=list)


class JavaASTParser:
    """Parser estrutural baseado em tokens para construir AST de código Java."""

    TYPE_KEYWORDS = {"class", "interface", "enum", "record"}

    def __init__(self) -> None:
        self.lexer = JavaLexer()

    def parse(
        self,
        source: str,
        *,
        expected_type_name: str | None = None,
    ) -> CompilationUnitNode:
        tokens = self.lexer.tokenize(source)
        unit = CompilationUnitNode()

        idx = 0
        pending_comments: list[str] = []
        pending_annotations: list[str] = []

        while idx < len(tokens):
            tok = tokens[idx]

            if tok.kind == "COMMENT":
                pending_comments.append(tok.value)
                idx += 1
                continue

            if tok.kind == "ANNOTATION":
                pending_annotations.append(tok.value)
                idx += 1
                continue

            if tok.kind == "WORD" and tok.value == "package":
                semi_idx = self._find_top_semi(tokens, idx)
                raw = source[tokens[idx].start : tokens[semi_idx].end].strip()
                pkg_name = raw[len("package") : -1].strip()
                unit.package = PackageNode(
                    name=pkg_name,
                    raw=raw,
                    leading_comments=pending_comments,
                    annotations=pending_annotations,
                )
                pending_comments, pending_annotations = [], []
                idx = semi_idx + 1
                continue

            if tok.kind == "WORD" and tok.value == "import":
                semi_idx = self._find_top_semi(tokens, idx)
                raw = source[tokens[idx].start : tokens[semi_idx].end].strip()
                is_static = "import static " in " ".join(raw.split())
                import_body = raw[len("import") : -1].strip()
                if is_static and import_body.startswith("static "):
                    import_body = import_body[len("static ") :].strip()
                unit.imports.append(
                    ImportNode(
                        path=import_body,
                        is_static=is_static,
                        raw=raw,
                        leading_comments=pending_comments,
                    )
                )
                pending_comments, pending_annotations = [], []
                idx = semi_idx + 1
                continue

            member, next_idx = self._parse_declaration(
                source,
                tokens,
                idx,
                pending_comments=pending_comments,
                pending_annotations=pending_annotations,
                enclosing_type_name=expected_type_name,
            )
            pending_comments, pending_annotations = [], []

            if isinstance(member, TypeDeclNode):
                unit.types.append(member)
            elif member is not None:
                unit.orphan_members.append(member)

            idx = next_idx

        return unit

    def _parse_declaration(
        self,
        source: str,
        tokens: list[JavaToken],
        start_idx: int,
        *,
        pending_comments: list[str],
        pending_annotations: list[str],
        enclosing_type_name: str | None = None,
    ) -> tuple[JavaASTNode | None, int]:
        n = len(tokens)
        idx = start_idx
        paren_depth = 0

        # Procura o delimitador estrutural da declaração (; ou {)
        while idx < n:
            tok = tokens[idx]
            if tok.kind == "LPAREN":
                paren_depth += 1
            elif tok.kind == "RPAREN" and paren_depth > 0:
                paren_depth -= 1
            elif paren_depth == 0 and tok.kind in ("SEMI", "LBRACE"):
                break
            idx += 1

        if idx >= n:
            raw = source[tokens[start_idx].start :].strip()
            if not raw:
                return None, n
            return (
                FieldNode(
                    name=self._extract_field_name(tokens[start_idx:]),
                    raw=raw,
                    leading_comments=pending_comments,
                    annotations=pending_annotations,
                ),
                n,
            )

        header_tokens = tokens[start_idx:idx]

        # Declaração terminada em ';' (campo ou método abstrato/de interface)
        if tokens[idx].kind == "SEMI":
            raw = source[tokens[start_idx].start : tokens[idx].end].strip()
            if self._looks_like_method_header(header_tokens):
                method_name, signature = self._extract_callable_signature(
                    header_tokens
                )
                return (
                    MethodNode(
                        name=method_name,
                        signature=signature,
                        raw=raw,
                        is_abstract=True,
                        leading_comments=pending_comments,
                        annotations=pending_annotations,
                    ),
                    idx + 1,
                )

            return (
                FieldNode(
                    name=self._extract_field_name(header_tokens),
                    raw=raw,
                    leading_comments=pending_comments,
                    annotations=pending_annotations,
                ),
                idx + 1,
            )

        # Se existe '=' antes do '{', trata-se de campo com inicializador de array/bloco
        if self._has_top_level_equals(header_tokens):
            semi_idx = self._find_statement_end_after_brace(tokens, idx)
            raw = source[tokens[start_idx].start : tokens[semi_idx].end].strip()
            return (
                FieldNode(
                    name=self._extract_field_name(header_tokens),
                    raw=raw,
                    leading_comments=pending_comments,
                    annotations=pending_annotations,
                ),
                semi_idx + 1,
            )

        # Verifica se é declaração de tipo (class, interface, enum, record)
        type_kw_pos = self._find_type_keyword(header_tokens)
        if type_kw_pos is not None:
            close_brace = self._find_matching_brace(tokens, idx)
            kind = header_tokens[type_kw_pos].value
            type_name = ""
            for t in header_tokens[type_kw_pos + 1 :]:
                if t.kind == "WORD":
                    type_name = t.value
                    break
            header_text = source[
                tokens[start_idx].start : tokens[idx].start
            ].strip()

            inner_tokens = tokens[idx + 1 : close_brace]
            members = self._parse_type_body(
                source,
                inner_tokens,
                enclosing_type_name=type_name or enclosing_type_name,
            )
            return (
                TypeDeclNode(
                    kind=kind,
                    name=type_name,
                    header=header_text,
                    members=members,
                    leading_comments=pending_comments,
                    annotations=pending_annotations,
                ),
                close_brace + 1,
            )

        # Bloco inicializador (static { ... } ou { ... })
        if not header_tokens or (
            len(header_tokens) == 1
            and header_tokens[0].kind == "WORD"
            and header_tokens[0].value == "static"
        ):
            close_brace = self._find_matching_brace(tokens, idx)
            raw = source[
                tokens[start_idx].start : tokens[close_brace].end
            ].strip()
            return (
                InitializerNode(
                    is_static=bool(header_tokens),
                    raw=raw,
                    leading_comments=pending_comments,
                    annotations=pending_annotations,
                ),
                close_brace + 1,
            )

        # Caso contrário, trata-se de construtor ou método com corpo
        close_brace = self._find_matching_brace(tokens, idx)
        raw = source[tokens[start_idx].start : tokens[close_brace].end].strip()
        callable_name, signature = self._extract_callable_signature(
            header_tokens
        )
        is_constructor = self._is_constructor_header(
            header_tokens,
            callable_name,
            enclosing_type_name=enclosing_type_name,
        )

        if is_constructor:
            return (
                ConstructorNode(
                    name=callable_name,
                    signature=signature,
                    raw=raw,
                    leading_comments=pending_comments,
                    annotations=pending_annotations,
                ),
                close_brace + 1,
            )

        return (
            MethodNode(
                name=callable_name,
                signature=signature,
                raw=raw,
                is_abstract=False,
                leading_comments=pending_comments,
                annotations=pending_annotations,
            ),
            close_brace + 1,
        )

    def _parse_type_body(
        self,
        source: str,
        tokens: list[JavaToken],
        *,
        enclosing_type_name: str | None,
    ) -> list[JavaASTNode]:
        members: list[JavaASTNode] = []
        idx = 0
        pending_comments: list[str] = []
        pending_annotations: list[str] = []

        while idx < len(tokens):
            tok = tokens[idx]
            if tok.kind == "COMMENT":
                pending_comments.append(tok.value)
                idx += 1
                continue
            if tok.kind == "ANNOTATION":
                pending_annotations.append(tok.value)
                idx += 1
                continue
            if tok.kind == "SEMI":
                idx += 1
                continue

            member, next_idx = self._parse_declaration(
                source,
                tokens,
                idx,
                pending_comments=pending_comments,
                pending_annotations=pending_annotations,
                enclosing_type_name=enclosing_type_name,
            )
            pending_comments, pending_annotations = [], []
            if member is not None:
                members.append(member)
            idx = next_idx

        return members

    @staticmethod
    def _find_top_semi(tokens: list[JavaToken], start: int) -> int:
        for i in range(start, len(tokens)):
            if tokens[i].kind == "SEMI":
                return i
        raise ValueError("Declaração Java incompleta: ';' esperado.")

    @staticmethod
    def _find_matching_brace(tokens: list[JavaToken], lbrace_idx: int) -> int:
        depth = 0
        for i in range(lbrace_idx, len(tokens)):
            if tokens[i].kind == "LBRACE":
                depth += 1
            elif tokens[i].kind == "RBRACE":
                depth -= 1
                if depth == 0:
                    return i
        raise ValueError("Bloco Java desbalanceado: '}' esperado.")

    def _find_statement_end_after_brace(
        self,
        tokens: list[JavaToken],
        lbrace_idx: int,
    ) -> int:
        close_brace = self._find_matching_brace(tokens, lbrace_idx)
        for i in range(close_brace + 1, len(tokens)):
            if tokens[i].kind == "SEMI":
                return i
        return close_brace

    @staticmethod
    def _has_top_level_equals(header_tokens: list[JavaToken]) -> bool:
        paren_depth = 0
        for tok in header_tokens:
            if tok.kind == "LPAREN":
                paren_depth += 1
            elif tok.kind == "RPAREN" and paren_depth > 0:
                paren_depth -= 1
            elif paren_depth == 0 and tok.kind == "SYMBOL" and tok.value == "=":
                return True
        return False

    def _find_type_keyword(self, header_tokens: list[JavaToken]) -> int | None:
        paren_depth = 0
        for i, tok in enumerate(header_tokens):
            if tok.kind == "LPAREN":
                paren_depth += 1
            elif tok.kind == "RPAREN" and paren_depth > 0:
                paren_depth -= 1
            elif paren_depth == 0 and tok.kind == "WORD" and tok.value in self.TYPE_KEYWORDS:
                return i
        return None

    @staticmethod
    def _looks_like_method_header(header_tokens: list[JavaToken]) -> bool:
        has_lparen = any(tok.kind == "LPAREN" for tok in header_tokens)
        has_equals = any(
            tok.kind == "SYMBOL" and tok.value == "=" for tok in header_tokens
        )
        return has_lparen and not has_equals

    @staticmethod
    def _extract_field_name(header_tokens: list[JavaToken]) -> str:
        before_eq = []
        for tok in header_tokens:
            if tok.kind == "SYMBOL" and tok.value == "=":
                break
            before_eq.append(tok)
        words = [tok.value for tok in before_eq if tok.kind == "WORD"]
        return words[-1] if words else "field"

    @staticmethod
    def _extract_callable_signature(
        header_tokens: list[JavaToken],
    ) -> tuple[str, str]:
        lparen_idx = None
        rparen_idx = None
        depth = 0
        for i, tok in enumerate(header_tokens):
            if tok.kind == "LPAREN" and lparen_idx is None:
                lparen_idx = i
                depth = 1
            elif tok.kind == "LPAREN":
                depth += 1
            elif tok.kind == "RPAREN":
                depth -= 1
                if depth == 0 and lparen_idx is not None:
                    rparen_idx = i
                    break

        if lparen_idx is None or rparen_idx is None:
            return "unknown", "unknown()"

        name = "unknown"
        for tok in reversed(header_tokens[:lparen_idx]):
            if tok.kind == "WORD":
                name = tok.value
                break

        param_tokens = header_tokens[lparen_idx + 1 : rparen_idx]
        params_sig = " ".join(tok.value for tok in param_tokens)
        return name, f"{name}({params_sig})"

    @staticmethod
    def _is_constructor_header(
        header_tokens: list[JavaToken],
        callable_name: str,
        *,
        enclosing_type_name: str | None,
    ) -> bool:
        if enclosing_type_name and callable_name == enclosing_type_name:
            return True
        modifiers = {
            "public",
            "protected",
            "private",
        }
        lparen_idx = next(
            (i for i, tok in enumerate(header_tokens) if tok.kind == "LPAREN"),
            len(header_tokens),
        )
        pre_words = [
            tok.value
            for tok in header_tokens[:lparen_idx]
            if tok.kind == "WORD" and tok.value not in modifiers
        ]
        # Em construtores sem tipo de retorno, resta apenas o próprio nome antes de '('
        return len(pre_words) == 1 and pre_words[0] == callable_name


class JavaASTRecomposer:
    """
    Reconstrói artefatos Java a partir dos fragmentos produzidos pelos
    StepNodes filhos usando a AST estrutural.
    """

    def __init__(self) -> None:
        self.parser = JavaASTParser()

    def recompose(
        self,
        contract: dict[str, Any],
        member_sources: list[tuple[dict[str, Any], str]],
    ) -> str:
        artifact = str(contract.get("artifact", "Generated.java"))
        structure = str(contract.get("structure", "class")).lower()
        target_name = str(
            contract.get("target_name") or Path(artifact).stem or "Generated"
        )
        target_kind = (
            structure
            if structure in ("class", "interface", "enum", "record")
            else "class"
        )

        package_node: PackageNode | None = None
        imports_by_key: dict[str, ImportNode] = {}
        type_header: str = f"public {target_kind} {target_name}"
        type_annotations: list[str] = []
        type_comments: list[str] = []

        fields_by_name: dict[str, FieldNode] = {}
        initializers: list[InitializerNode] = []
        constructors_by_sig: dict[str, ConstructorNode] = {}
        methods_by_sig: dict[str, MethodNode] = {}
        nested_types: dict[str, TypeDeclNode] = {}

        for member_spec, raw_code in member_sources:
            role = str(member_spec.get("role", "body")).lower()
            cleaned = strip_markdown_fences(raw_code)
            unit = self.parser.parse(cleaned, expected_type_name=target_name)

            if unit.package and package_node is None:
                package_node = unit.package

            for imp in unit.imports:
                imports_by_key[imp.raw] = imp

            extracted_members: list[JavaASTNode] = list(unit.orphan_members)
            for tdecl in unit.types:
                if tdecl.name == target_name or len(unit.types) == 1:
                    if tdecl.header and (
                        "extends" in tdecl.header
                        or "implements" in tdecl.header
                        or role in ("header", "declaration", "class", "body", "all")
                    ):
                        type_header = tdecl.header
                    type_annotations.extend(tdecl.annotations)
                    type_comments.extend(tdecl.leading_comments)
                    extracted_members.extend(tdecl.members)
                else:
                    nested_types[tdecl.name] = tdecl

            for node in extracted_members:
                if not self._role_accepts(role, node):
                    continue

                if isinstance(node, FieldNode):
                    fields_by_name[node.name] = node
                elif isinstance(node, InitializerNode):
                    initializers.append(node)
                elif isinstance(node, ConstructorNode):
                    constructors_by_sig[node.signature] = node
                elif isinstance(node, MethodNode):
                    methods_by_sig[node.signature] = node
                elif isinstance(node, TypeDeclNode):
                    nested_types[node.name] = node

        ordered_members: list[JavaASTNode] = [
            *fields_by_name.values(),
            *initializers,
            *constructors_by_sig.values(),
            *methods_by_sig.values(),
            *nested_types.values(),
        ]

        target_type = TypeDeclNode(
            kind=target_kind,
            name=target_name,
            header=type_header,
            members=ordered_members,
            leading_comments=list(dict.fromkeys(type_comments)),
            annotations=list(dict.fromkeys(type_annotations)),
        )

        final_unit = CompilationUnitNode(
            package=package_node,
            imports=list(imports_by_key.values()),
            types=[target_type],
        )

        rendered = self._render_compilation_unit(final_unit)
        # Verifica integridade sintática re-parseando a AST recomposta
        self.parser.parse(rendered, expected_type_name=target_name)
        return rendered

    @staticmethod
    def _role_accepts(role: str, node: JavaASTNode) -> bool:
        if role in ("body", "all", "members", "class", "interface"):
            return True
        if role in ("attributes", "fields", "properties"):
            return isinstance(node, (FieldNode, InitializerNode))
        if role in ("constructor", "constructors"):
            return isinstance(node, ConstructorNode)
        if role in ("methods", "method"):
            return isinstance(node, MethodNode)
        if role in ("inner_types", "nested"):
            return isinstance(node, TypeDeclNode)
        return True

    def _render_compilation_unit(self, unit: CompilationUnitNode) -> str:
        sections: list[str] = []

        if unit.package is not None:
            sections.append(unit.package.raw)

        if unit.imports:
            sections.append("\n".join(imp.raw for imp in unit.imports))

        for tdecl in unit.types:
            sections.append(self._render_type(tdecl, indent=0))

        return "\n\n".join(sections).strip() + "\n"

    def _render_type(self, tdecl: TypeDeclNode, *, indent: int) -> str:
        prefix = "    " * indent
        lines: list[str] = []

        for comment in tdecl.leading_comments:
            lines.append(self._indent_block(comment, indent))
        for annotation in tdecl.annotations:
            lines.append(f"{prefix}{annotation}")

        lines.append(f"{prefix}{tdecl.header} {{")

        for idx, member in enumerate(tdecl.members):
            if idx > 0:
                lines.append("")
            lines.append(self._render_member(member, indent=indent + 1))

        lines.append(f"{prefix}}}")
        return "\n".join(lines)

    def _render_member(self, member: JavaASTNode, *, indent: int) -> str:
        prefix = "    " * indent
        lines: list[str] = []

        for comment in member.leading_comments:
            lines.append(self._indent_block(comment, indent))
        for annotation in member.annotations:
            lines.append(f"{prefix}{annotation}")

        if isinstance(member, TypeDeclNode):
            lines.append(self._render_type(member, indent=indent))
        else:
            raw = getattr(member, "raw", "")
            lines.append(self._indent_block(raw, indent))

        return "\n".join(lines)

    @staticmethod
    def _indent_block(text: str, indent: int) -> str:
        prefix = "    " * indent
        raw_lines = text.strip().splitlines()
        if not raw_lines:
            return ""
        # Remove indentação comum existente antes de reindentar de forma canônica
        non_empty = [line for line in raw_lines[1:] if line.strip()]
        min_ws = (
            min(len(line) - len(line.lstrip()) for line in non_empty)
            if non_empty
            else 0
        )
        normalized = [raw_lines[0].lstrip()] + [
            line[min_ws:] if len(line) >= min_ws else line.lstrip()
            for line in raw_lines[1:]
        ]
        return "\n".join(
            f"{prefix}{line}" if line.strip() else ""
            for line in normalized
        )


# ============================================================================
# AST Recomposer para Python (stdlib ast)
# ============================================================================


class PythonASTRecomposer:
    """
    Reconstrói módulos e classes Python usando o módulo padrão `ast`.
    """

    def recompose(
        self,
        contract: dict[str, Any],
        member_sources: list[tuple[dict[str, Any], str]],
    ) -> str:
        artifact = str(contract.get("artifact", "generated.py"))
        structure = str(contract.get("structure", "module")).lower()
        target_name = str(
            contract.get("target_name") or Path(artifact).stem or "Generated"
        )

        imports_by_dump: dict[str, ast.stmt] = {}
        class_bases: list[ast.expr] = []
        class_keywords: list[ast.keyword] = []
        class_decorators: list[ast.expr] = []
        class_docstring: ast.Expr | None = None

        attributes: list[ast.stmt] = []
        constructors: dict[str, ast.FunctionDef] = {}
        methods: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
        module_classes: dict[str, ast.ClassDef] = {}
        module_functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
        extra_statements: list[ast.stmt] = []

        for member_spec, raw_code in member_sources:
            role = str(member_spec.get("role", "body")).lower()
            cleaned = strip_markdown_fences(raw_code)
            parsed = ast.parse(cleaned)

            for stmt in parsed.body:
                if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                    imports_by_dump[ast.dump(stmt)] = stmt
                    continue

                if structure == "class":
                    if isinstance(stmt, ast.ClassDef):
                        if not class_bases and stmt.bases:
                            class_bases = list(stmt.bases)
                        if not class_keywords and stmt.keywords:
                            class_keywords = list(stmt.keywords)
                        if not class_decorators and stmt.decorator_list:
                            class_decorators = list(stmt.decorator_list)
                        for inner in stmt.body:
                            self._collect_class_stmt(
                                inner,
                                role=role,
                                attributes=attributes,
                                constructors=constructors,
                                methods=methods,
                                extra_statements=extra_statements,
                                docstring_holder=lambda d: None,
                            )
                            if (
                                class_docstring is None
                                and isinstance(inner, ast.Expr)
                                and isinstance(inner.value, ast.Constant)
                                and isinstance(inner.value.value, str)
                            ):
                                class_docstring = inner
                    else:
                        self._collect_class_stmt(
                            stmt,
                            role=role,
                            attributes=attributes,
                            constructors=constructors,
                            methods=methods,
                            extra_statements=extra_statements,
                            docstring_holder=lambda d: None,
                        )
                else:
                    if isinstance(stmt, ast.ClassDef):
                        module_classes[stmt.name] = stmt
                    elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        module_functions[stmt.name] = stmt
                    else:
                        extra_statements.append(stmt)

        final_body: list[ast.stmt] = list(imports_by_dump.values())

        if structure == "class":
            class_body: list[ast.stmt] = []
            if class_docstring is not None:
                class_body.append(class_docstring)
            class_body.extend(attributes)
            class_body.extend(constructors.values())
            class_body.extend(methods.values())
            class_body.extend(extra_statements)
            if not class_body:
                class_body.append(ast.Pass())

            class_def = ast.ClassDef(
                name=target_name,
                bases=class_bases,
                keywords=class_keywords,
                body=class_body,
                decorator_list=class_decorators,
            )
            final_body.append(class_def)
        else:
            final_body.extend(attributes)
            final_body.extend(module_classes.values())
            final_body.extend(module_functions.values())
            final_body.extend(extra_statements)

        module = ast.Module(body=final_body, type_ignores=[])
        ast.fix_missing_locations(module)
        rendered = ast.unparse(module) + "\n"
        ast.parse(rendered)
        return rendered

    @staticmethod
    def _collect_class_stmt(
        stmt: ast.stmt,
        *,
        role: str,
        attributes: list[ast.stmt],
        constructors: dict[str, ast.FunctionDef],
        methods: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
        extra_statements: list[ast.stmt],
        docstring_holder: Any,
    ) -> None:
        if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            if role in ("attributes", "fields", "properties", "body", "all", "class"):
                attributes.append(stmt)
        elif isinstance(stmt, ast.FunctionDef):
            if stmt.name in ("__init__", "__new__") and role in (
                "constructor",
                "constructors",
                "attributes",
                "body",
                "all",
                "class",
            ):
                constructors[stmt.name] = stmt
            elif role in ("methods", "method", "functions", "body", "all", "class"):
                methods[stmt.name] = stmt
        elif isinstance(stmt, ast.AsyncFunctionDef):
            if role in ("methods", "method", "functions", "body", "all", "class"):
                methods[stmt.name] = stmt
        elif not (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str)
        ):
            extra_statements.append(stmt)


# ============================================================================
# Container Recomposer do Code Breaker
# ============================================================================


class Recomposer:
    """
    Container do Code Breaker responsável por reconstruir o artefato esperado
    por um StepNode pai a partir dos resultados dos StepNodes filhos.
    """

    def __init__(self) -> None:
        self.python_recomposer = PythonASTRecomposer()
        self.java_recomposer = JavaASTRecomposer()

    def validate_contract(
        self,
        contract: dict[str, Any] | None,
        child_nodes: list[StepNode],
    ) -> dict[str, Any]:
        """Valida se o contrato de recomposição está bem formado e completo."""
        if not isinstance(contract, dict):
            raise ValueError("Contrato de recomposição deve ser um dicionário.")

        artifact = contract.get("artifact")
        structure = contract.get("structure")
        members = contract.get("members")

        if not isinstance(artifact, str) or not artifact.strip():
            raise ValueError("Contrato de recomposição exige 'artifact' válido.")
        if not isinstance(structure, str) or not structure.strip():
            raise ValueError("Contrato de recomposição exige 'structure' válido.")
        if not isinstance(members, list) or not members:
            raise ValueError("Contrato de recomposição exige 'members' não vazio.")

        for entry in members:
            if not isinstance(entry, dict):
                raise ValueError("Cada entrada de 'members' deve ser um objeto.")
            if "source_node" not in entry:
                raise ValueError("Cada membro deve definir 'source_node'.")
            role = entry.get("role")
            if not isinstance(role, str) or not role.strip():
                raise ValueError("Cada membro deve definir 'role' válido.")
            self._resolve_source_node(entry["source_node"], child_nodes)

        return contract

    def recompose(
        self,
        parent_node: StepNode,
        child_nodes: list[StepNode],
    ) -> str:
        """
        Integra os resultados dos filhos conforme o contrato de recomposição
        usando algoritmo baseado em AST.
        """
        contract = self.validate_contract(
            parent_node.recomposition_contract,
            child_nodes,
        )

        member_sources: list[tuple[dict[str, Any], str]] = []
        for entry in contract["members"]:
            child = self._resolve_source_node(entry["source_node"], child_nodes)
            if not isinstance(child.result, str) or not child.result.strip():
                raise ValueError(
                    f"StepNode filho '{child.id}' ainda não possui resultado válido."
                )
            member_sources.append((entry, child.result))

        artifact = str(contract["artifact"]).lower()
        if artifact.endswith(".py"):
            return self.python_recomposer.recompose(contract, member_sources)

        if artifact.endswith((".java", ".cs", ".ts", ".js")):
            return self.java_recomposer.recompose(contract, member_sources)

        # Fallback estruturado para artefatos não pertencentes a AST Python/Java
        parts = [
            strip_markdown_fences(raw_code)
            for _, raw_code in member_sources
        ]
        return "\n\n".join(parts).strip() + "\n"

    @staticmethod
    def _resolve_source_node(
        source_ref: int | str,
        child_nodes: list[StepNode],
    ) -> StepNode:
        ref_str = str(source_ref).strip()
        for child in child_nodes:
            if child.id == ref_str:
                return child
            if child.local_id is not None and str(child.local_id) == ref_str:
                return child
        raise KeyError(
            f"source_node '{source_ref}' não corresponde a nenhum filho."
        )
