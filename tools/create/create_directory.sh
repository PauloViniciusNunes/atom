#!/bin/bash
set -euo pipefail

if [ "$#" -lt 1 ]; then
    echo "Uso: $0 <caminho_do_diretorio> [outros_diretorios...]" >&2
    exit 1
fi

for target in "$@"; do
    if [ -z "$target" ] || [ "$target" = "/" ]; then
        echo "Caminho inválido para criação de diretório: '$target'" >&2
        exit 1
    fi

    if [ -e "$target" ] && [ ! -d "$target" ]; then
        echo "Erro: '$target' já existe e não é um diretório." >&2
        exit 1
    fi

    mkdir -p -- "$target"
done
