#!/bin/bash
set -euo pipefail

if [ "$#" -lt 1 ]; then
    echo "Uso: $0 <caminho_do_diretorio> [outros_diretorios...]" >&2
    exit 1
fi

for target in "$@"; do
    if [ -z "$target" ] || [ "$target" = "." ] || [ "$target" = ".." ] || [ "$target" = "/" ]; then
        echo "Caminho proibido para remoção de diretório: '$target'" >&2
        exit 1
    fi

    if [ ! -e "$target" ]; then
        echo "Erro: diretório '$target' não encontrado." >&2
        exit 1
    fi

    if [ ! -d "$target" ]; then
        echo "Erro: '$target' não é um diretório; utilize delete_archive.sh." >&2
        exit 1
    fi

    rm -rf -- "$target"
done
