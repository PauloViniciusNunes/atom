#!/bin/bash
set -euo pipefail

if [ "$#" -ne 3 ]; then
    echo "Uso: $0 <caminho_do_arquivo> <texto_alvo> <texto_substituto>" >&2
    exit 1
fi

target="$1"
old_text="$2"
new_text="$3"

if [ ! -f "$target" ]; then
    echo "Erro: arquivo '$target' não encontrado." >&2
    exit 1
fi

if [ -z "$old_text" ]; then
    echo "Erro: texto_alvo não pode ser vazio." >&2
    exit 1
fi

python3 - "$target" "$old_text" "$new_text" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
old = sys.argv[2]
new = sys.argv[3]

content = path.read_text(encoding="utf-8")
if old not in content:
    sys.stderr.write(f"Erro: trecho alvo não encontrado em '{path}'.\n")
    sys.exit(1)

path.write_text(content.replace(old, new, 1), encoding="utf-8")
PY
