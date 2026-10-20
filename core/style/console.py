from pyfiglet import Figlet
from rich.console import Console
from rich.panel import Panel
from rich.align import Align

console = Console()

# Identidade visual dos logs do ATOM
class Console:

    def __init__(self):
        pass

    def log(self, message: str):
        if len(message) <= 0:
            return

        console.print(f'[[bold cyan]ATOM[/bold cyan]] {message}.')

    def error(self, message: str):
        if len(message) <= 0:
            return        

        console.print(f'[red][[bold]ERROR[/bold]] [italic]{message}.[/italic][/red]')
        
    def sucess(self, message: str):
        if len(message) <= 0:
            return

        console.print(f'[green][[bold]SUCESS[/bold]] {message}.[/green]')
        
    def warn(self, message: str):
        if len(message) <= 0:
            return

        console.print(f'[yellow][[bold]WARNING[/bold]] {message}.[/yellow]')        