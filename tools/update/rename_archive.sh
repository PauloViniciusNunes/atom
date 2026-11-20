#!/bin/bash
set -euo pipefail

if [ "$#" -ne 2 ]; then
    echo "Uso: $0 <origem> <destino>" >&2
    exit 1
fi

src="$1"
dst="$2"

if [ -z "$src" ] || [ -z "$dst" ] || [ "$src" = "/" ] || [ "$dst" = "/" ]; then
    echo "Caminho inválido para movimentação/renomeação." >&2
    exit 1
fi

if [ ! -e "$src" ]; then
    echo "Erro: origem '$src' não encontrada." >&2
    exit 1
fi

if [ -e "$dst" ]; then
    echo "Erro: destino '$dst' já existe." >&2
    exit 1
fi

parent_dir="$(dirname -- "$dst")"
if [ -n "$parent_dir" ] && [ "$parent_dir" != "." ]; then
    mkdir -p -- "$parent_dir"
fi

mv -- "$src" "$dst"
