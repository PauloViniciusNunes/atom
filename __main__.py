import argparse
from pathlib import Path

from core.runtime.runtime import Runtime
from core.state.states import TaskState
from core.style.banner import show_banner
from core.style.console import Console
from core.tools_management.tool_manager import ToolRegistry


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Interpreta argumentos de linha de comando do ATOM."""
    parser = argparse.ArgumentParser(
        prog="atom",
        description="ATOM - Autonomous Task Orchestrator",
    )
    parser.add_argument(
        "-w",
        "--workspace",
        type=Path,
        default=None,
        help="Diretório do projeto alvo (padrão: diretório atual).",
    )
    parser.add_argument(
        "-t",
        "--task",
        type=str,
        default=None,
        help="Executa uma única tarefa em modo não interativo e encerra.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Força aplicação de efeitos em disco via ToolRegistry (já ativo por padrão).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Executa o pipeline apenas em memória sem aplicar alterações em disco.",
    )
    return parser.parse_args(argv)


def run_single_task(
    runtime: Runtime,
    console: Console,
    goal: str,
) -> TaskState:
    """Executa o pipeline completo para um objetivo textual."""
    task = runtime.create_task(goal)
    runtime.inspect_project(task)

    console.log("Processado..")

    task = runtime.plan_task(task)

    print(task.plan_proposal)
    console.log(f"Passos totais {task.total_steps}")

    runtime.do_task(task)

    if task.state == TaskState.COMPLETED:
        console.sucess("Concluído!")
    else:
        console.error(f"Execução encerrada com estado: {task.state.name}")

    console.log(f"Estado atual: {task.state.name}")
    if task.final_report is not None:
        print(task.final_report)

    assert task.state in (
        TaskState.COMPLETED,
        TaskState.BLOCKED,
        TaskState.FAILED,
    )
    return task.state


def main(argv: list[str] | None = None) -> int:
    """Ponto de entrada principal do ATOM."""
    args = parse_args(argv)
    workspace_root = (
        args.workspace.resolve()
        if args.workspace is not None
        else Path.cwd().resolve()
    )

    apply_effects = True if args.apply else (not args.dry_run)

    console = Console()
    registry = ToolRegistry(workspace_root=workspace_root)
    runtime = Runtime(
        workspace_root=workspace_root,
        registry=registry,
        apply_effects=apply_effects,
    )

    show_banner()
    console.log(f"Workspace ativo: {workspace_root}")
    console.log(
        f"ToolRegistry ativo com {len(registry.registries)} ferramentas "
        f"(apply_effects={apply_effects})."
    )

    if args.task is not None:
        final_state = run_single_task(runtime, console, args.task)
        return 0 if final_state == TaskState.COMPLETED else 1

    try:
        while True:
            usr_input: str = input(">>> Task: ")
            if not usr_input.strip():
                continue
            run_single_task(runtime, console, usr_input)
    except (EOFError, KeyboardInterrupt):
        console.log("Encerrando..")
    finally:
        console.log("Até logo!")

    return 0


# Execução principal do agente
if __name__ == "__main__":
    raise SystemExit(main())
