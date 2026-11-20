#!/bin/bash
set -euo pipefail

if [ "$#" -ne 2 ]; then
    echo "Uso: $0 <conteudo> <caminho_do_arquivo>" >&2
    exit 1
fi

content="$1"
target="$2"

if [ -z "$target" ] || [ "$target" = "." ] || [ "$target" = ".." ] || [ "$target" = "/" ]; then
    echo "Caminho inválido para adição de conteúdo: '$target'" >&2
    exit 1
fi

if [ -d "$target" ]; then
    echo "Erro: '$target' é um diretório." >&2
    exit 1
fi

parent_dir="$(dirname -- "$target")"
if [ -n "$parent_dir" ] && [ "$parent_dir" != "." ]; then
    mkdir -p -- "$parent_dir"
fi

printf '%s' "$content" >> "$target"
