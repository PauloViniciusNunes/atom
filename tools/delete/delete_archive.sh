#!/bin/bash
set -euo pipefail

if [ "$#" -lt 1 ]; then
    echo "Uso: $0 <caminho_do_arquivo> [outros_arquivos...]" >&2
    exit 1
fi

for target in "$@"; do
    if [ -z "$target" ] || [ "$target" = "." ] || [ "$target" = ".." ] || [ "$target" = "/" ]; then
        echo "Caminho proibido para remoção de arquivo: '$target'" >&2
        exit 1
    fi

    if [ ! -e "$target" ] && [ ! -L "$target" ]; then
        echo "Erro: arquivo '$target' não encontrado." >&2
        exit 1
    fi

    if [ -d "$target" ] && [ ! -L "$target" ]; then
        echo "Erro: '$target' é um diretório; utilize delete_directory.sh." >&2
        exit 1
    fi

    rm -f -- "$target"
done
