from core.runtime.runtime import Runtime
from core.state.states import TaskState
from core.style.banner import show_banner
from core.style.console import Console

runtime = Runtime()
console = Console()

#Execução principal do agente
if __name__ == "__main__":

    show_banner()

    try:
        while True:

            usr_input: str = input(">>> Task: ")

            task = runtime.create_task(usr_input)

            console.log("Processado..")

            task = runtime.plan_task(task)

            print(task.plan_proposal)
            console.log(f'Passos totais {task.total_steps}')

            runtime.do_task(task)

            console.sucess("Concluído!")
            console.log(f'Estado atual: {task.state.name}')

            assert task.state in (TaskState.PLANNING, TaskState.FAILED)

    except (EOFError, KeyboardInterrupt):
        console.log("Encerrando..")
    finally:
        console.log("Até logo!")
