import subprocess
import shlex  # Importante para tratar as aspas e caracteres especiais no shell
from enum import Enum

class ToolType(Enum):
    CREATE = 1
    READ = 2
    UPDATE = 3
    DELETE = 4
    COMPILE = 5
    EXECUTE = 6

class ToolData:
    def __init__(self, id: int, type: ToolType, path: str, desc: str) -> None:
        self.id = id
        self.type = type
        self.path = path
        self.desc = desc

class ToolRegistry:

    # Registra uma tool
    registries: list[ToolData] = []

    def registry(self, id: int, type: ToolType, path: str, desc: str):
        newTool: ToolData = ToolData(id, type, path, desc)
        self.registries.append(newTool)

    def __init__(self) -> None:

        self.registry(1, ToolType.CREATE, ‘tools/create_file.sh’, “Cria um arquivo com o comando touch. Os argumentos passados representam arquivos a serem criados.”)
        self.registry(2, ToolType.UPDATE, ‘tools/write_file.sh’, “Escreve um conteúdo textual em um arquivo. Deve ser um arquivo com extensão de texto ou código.”)
        self.registry(3, ToolType.COMPILE, ‘tools/compile_c_archive.sh’, “Compila um arquivo de extensão ‘.c’.”)
        self.registry(4, ToolType.EXECUTE, ‘./source’, “Executa o arquivo binário source criado.”)

    def find(self, tool_id: int):

        if not isinstance(tool_id, int):
            raise ValueError(“O valor de tool_id era para ser inteiro.”)

        for r in self.registries:

            if r.id == tool_id:
                return r

        raise ValueError(f”tool id não foi encontrado para o valor {tool_id}“)

    def execute_tool(self, tool_id: int, args: list[str] = []):

        if not isinstance(tool_id, int):
            raise ValueError(“Esperado tipo int para tool_id em execute_tool.”)

        tool: ToolData = self.find(tool_id)
        path = tool.path

        if isinstance(args, list):
            # shlex.quote garante que strings com quebras de linha (\n) e aspas (“)
            # sejam passadas com segurança para o terminal sem quebrar o comando Bash
            args_seguros = [shlex.quote(str(arg)) for arg in args]

            exec_args = ' ‘.join(args_seguros)
            exec_args = f’{path} {exec_args}'
        else:
            raise ValueError(“O valor passado para args não corresponde a um tipo esperado na função.”)

        try:
            result = subprocess.run(exec_args, check=True, shell=True, capture_output=True, timeout=30)
            return result
        except Exception as error:
            print(error)
            return None

registry = ToolRegistry()

registry.execute_tool(1,[‘source.c’])

conteudo_c = ‘#include<stdio.h>\n\nint main(){\n    for(int i = 0; i < 100; i++){\n     printf(“Roblox is life!”);\n}\n   return(0);\n}\n’

registry.execute_tool(2, [conteudo_c, “source.c”])
registry.execute_tool(3, [‘source.c’, ‘source’])
registry.execute_tool(4)