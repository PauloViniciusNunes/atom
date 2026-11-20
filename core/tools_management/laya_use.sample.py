
import os

os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"

from laya import Router

router = Router(device="cpu")
router.preload(["multilingual"])

questions = {
    "tool": {
        "type": "choice",
        "instructions": "Qual ferramenta deve atender à solicitação do usuário?",
        "criteria": {
            "create": "Criar arquivos ou diretórios",
            "read": "Ler arquivos ou conteúdos de diretórios",
            "update": "Modificar arquivos existentes",
            "delete": "Excluir arquivos ou diretórios",
            "other": "Solicitações que não correspondem a essas ferramentas"
        }
    }
}

# Um caso de teste para cada ferramenta.
test_cases = {
    "create": "Crie uma pasta chamada geometria e um arquivo Quadrado.java dentro dela.",
    "read": "Leia o conteúdo do arquivo geometria/Quadrado.java.",
    "update": "Modifique o método calcularArea() no arquivo Quadrado.java.",
    "delete": "Exclua a pasta geometria e o arquivo Quadrado.java dentro dela.",
    "other": "Explique o conceito de herança em Java."
}

for expected, state in test_cases.items():
    result = router.predict(state, questions, lang="pt-BR")
    answer = result["answers"]["tool"]

    print("\n" + "=" * 60)
    print(f"Caso esperado: {expected}")
    print(f"Solicitação: {state}")
    print(f"Ferramenta selecionada: {answer['choice']}")
    print(f"Classificação correta: {answer['choice'] == expected}")
    print(f"Probabilidade por opção: {answer['probabilities']}")
    print(f"Confiança da resposta: {answer['answer_confidence']:.4f}")
    print(f"Concentração da distribuição: {answer['confidence']:.4f}")
    print(f"Modelo utilizado: {result['routing']['model']}")
