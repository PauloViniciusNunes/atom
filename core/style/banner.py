from pyfiglet import Figlet
from rich.console import Console
from rich.panel import Panel
from rich.align import Align

console = Console()

def show_banner():
    logo = Figlet(font="block").renderText("ATOM")

    console.print(
        Panel(
            Align.center(f"[bold cyan]{logo}[/bold cyan]"),
            subtitle="[dim]Autonomous Task Orchestrator[/dim]",
            border_style="blue",
            padding=(1, 2),
        )
    )
