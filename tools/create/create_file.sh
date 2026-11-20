#!/bin/bash
set -euo pipefail

if [ "$#" -lt 1 ]; then
    echo "Uso: $0 <caminho_do_arquivo> [outros_arquivos...]" >&2
    exit 1
fi

for target in "$@"; do
    if [ -z "$target" ] || [ "$target" = "." ] || [ "$target" = ".." ] || [ "$target" = "/" ]; then
        echo "Caminho inválido para criação de arquivo: '$target'" >&2
        exit 1
    fi

    if [ -d "$target" ]; then
        echo "Erro: '$target' já existe como diretório." >&2
        exit 1
    fi

    parent_dir="$(dirname -- "$target")"
    if [ -n "$parent_dir" ] && [ "$parent_dir" != "." ]; then
        mkdir -p -- "$parent_dir"
    fi

    touch -- "$target"
done
