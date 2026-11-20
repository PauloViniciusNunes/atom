#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
ATOM_HOME="$(cd "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd)"
BIN_DIR="${ATOM_BIN_DIR:-$HOME/.local/bin}"
TARGET_LINK="$BIN_DIR/atom"

usage() {
    cat <<EOF
Uso: $(basename "$0") [opções]

Configura o ambiente do ATOM e instala o comando 'atom' para execução em qualquer repositório.

Opções:
  --bin-dir <dir>   Diretório de instalação do comando (padrão: \$HOME/.local/bin)
  --uninstall       Remove o link simbólico instalado do comando 'atom'
  -h, --help        Exibe esta ajuda
EOF
}

UNINSTALL=false

while [ "$#" -gt 0 ]; do
    case "$1" in
        --bin-dir)
            if [ "$#" -lt 2 ]; then
                echo "Erro: --bin-dir exige um argumento." >&2
                exit 1
            fi
            BIN_DIR="$2"
            TARGET_LINK="$BIN_DIR/atom"
            shift 2
            ;;
        --uninstall)
            UNINSTALL=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Opção desconhecida: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

if [ "$UNINSTALL" = true ]; then
    if [ -L "$TARGET_LINK" ] || [ -f "$TARGET_LINK" ]; then
        rm -f "$TARGET_LINK"
        echo "[ATOM] Comando removido de: $TARGET_LINK"
    else
        echo "[ATOM] Nenhum comando encontrado em: $TARGET_LINK"
    fi
    exit 0
fi

echo "[ATOM] Raiz do projeto: $ATOM_HOME"

# 1. Garante ambiente virtual Python
if [ ! -x "$ATOM_HOME/.venv/bin/python" ]; then
    if ! command -v python3 >/dev/null 2>&1; then
        echo "Erro: python3 não encontrado no sistema." >&2
        exit 1
    fi
    echo "[ATOM] Criando ambiente virtual em $ATOM_HOME/.venv..."
    python3 -m venv "$ATOM_HOME/.venv"
fi

VENV_PYTHON="$ATOM_HOME/.venv/bin/python"

# 2. Instala dependências caso exista requirements.txt
if [ -f "$ATOM_HOME/requirements.txt" ]; then
    echo "[ATOM] Instalando dependências de requirements.txt..."
    "$VENV_PYTHON" -m pip install -r "$ATOM_HOME/requirements.txt"
fi

# 3. Garante permissões de execução nas tools e scripts de env
echo "[ATOM] Ajustando permissões de execução em tools/ e env/..."
find "$ATOM_HOME/tools" -type f -name "*.sh" -exec chmod +x {} +
chmod +x "$ATOM_HOME/env/atom" "$ATOM_HOME/env/build.sh" "$ATOM_HOME/env/env.sh"

# 4. Valida importações principais do núcleo (sem acionar Ollama)
echo "[ATOM] Validando módulos principais do ATOM..."
PYTHONPATH="$ATOM_HOME" "$VENV_PYTHON" -c "import core.runtime.runtime, core.code_breaker, core.pipeline, core.tools_management.tool_manager"

# 5. Instala o comando global no diretório de binários do usuário
mkdir -p "$BIN_DIR"
ln -sf "$ATOM_HOME/env/atom" "$TARGET_LINK"

echo "[ATOM] Comando instalado em: $TARGET_LINK -> $ATOM_HOME/env/atom"

case ":$PATH:" in
    *":$BIN_DIR:"*)
        echo "[ATOM] '$BIN_DIR' já está no PATH. Você já pode executar 'atom' de qualquer repositório."
        ;;
    *)
        echo "[ATOM] ATENÇÃO: '$BIN_DIR' não está no seu PATH atual."
        echo "Adicione a linha abaixo ao seu ~/.bashrc ou ~/.zshrc:"
        echo "  export PATH=\"$BIN_DIR:\$PATH\""
        ;;
esac
