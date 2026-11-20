#!/bin/bash

# Carregue este arquivo com: source env/env.sh
_ATOM_ENV_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
export ATOM_HOME="$(cd "$_ATOM_ENV_DIR/.." >/dev/null 2>&1 && pwd)"

case ":$PATH:" in
    *":$_ATOM_ENV_DIR:"*) ;;
    *) export PATH="$_ATOM_ENV_DIR:$PATH" ;;
esac

case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *) export PATH="$HOME/.local/bin:$PATH" ;;
esac
