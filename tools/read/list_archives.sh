#!/bin/bash
set -euo pipefail

target="${1:-.}"
max_depth="${2:-3}"

if [ ! -d "$target" ]; then
    echo "Erro: diretório '$target' não encontrado." >&2
    exit 1
fi

if ! [[ "$max_depth" =~ ^[0-9]+$ ]] || [ "$max_depth" -lt 1 ]; then
    echo "Erro: profundidade máxima deve ser um inteiro >= 1." >&2
    exit 1
fi

find "$target" -maxdepth "$max_depth" \
    \( -name ".git" -o -name ".venv" -o -name "__pycache__" -o -name "node_modules" \) -prune \
    -o -print | sort
