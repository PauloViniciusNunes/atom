#!/bin/bash
set -euo pipefail

if [ "$#" -lt 1 ] || [ "$#" -gt 3 ]; then
    echo "Uso: $0 <caminho_do_arquivo> [linha_inicial] [linha_final]" >&2
    exit 1
fi

target="$1"

if [ ! -f "$target" ]; then
    echo "Erro: arquivo '$target' não encontrado ou não é um arquivo regular." >&2
    exit 1
fi

if [ "$#" -eq 1 ]; then
    cat -- "$target"
    exit 0
fi

start_line="$2"
end_line="${3:-$start_line}"

if ! [[ "$start_line" =~ ^[0-9]+$ ]] || ! [[ "$end_line" =~ ^[0-9]+$ ]]; then
    echo "Erro: linha_inicial e linha_final devem ser inteiros positivos." >&2
    exit 1
fi

if [ "$start_line" -lt 1 ] || [ "$end_line" -lt "$start_line" ]; then
    echo "Erro: intervalo de linhas inválido (${start_line}..${end_line})." >&2
    exit 1
fi

sed -n "${start_line},${end_line}p" -- "$target"
