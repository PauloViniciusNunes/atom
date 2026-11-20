Nossa estratégia para o **pipeline de execução do ATOM** é construir um agente híbrido: o modelo de IA propõe soluções, mas o núcleo determinístico controla o processo, valida as decisões e determina quando uma tarefa realmente foi concluída.

A ideia central é: **não confiar cegamente no modelo, mas também não desperdiçar sua capacidade de interpretação e geração.**

## **1. Arquitetura geral**

Trabalhamos com três elementos principais:

Modelo generativo

**Ollama**

Interpretação, planejamento, geração de código e análise de problemas.

Autoridade central

**Núcleo determinístico do ATOM**

Gerencia contexto, contratos, dependências, permissões, ferramentas, execução, validação e estados.

Execução

**Registry e ferramentas**

Scripts e operações autorizadas que interagem com o sistema operacional e os projetos.

**Verificador**

Compara o resultado real com os critérios de conclusão.

Também exploramos o uso do **Laya** como classificador especializado para identificar intenções e categorias de ferramentas. Ele não substitui o planejamento generativo do Ollama.

## **2. Pipeline de execução**

A sequência que estruturamos foi esta:

1. **Inspecionar o projeto**

   O ATOM analisa o ambiente atual: estrutura de diretórios, arquivos, componentes, dependências, assinaturas e estado do projeto.

   O objetivo é construir uma representação contextual do que já existe, evitando que o modelo precise receber todo o código.
2. **Planejar a tarefa**

   O Ollama recebe o contexto relevante e propõe um plano estruturado, dividido em etapas.

   Cada etapa deve possuir:
   - Identificador.
   - Descrição.
   - Contratos, com precondições, póscondições e invariantes.
   - Efeitos de Operações.
   - Critérios de conclusão.
   - Dependências de outras etapas.
   - Dados de Decomposição
3. **Validar o plano**

   O núcleo determinístico verifica se o plano é coerente e executável:
   - Estrutura e formato dos dados.
   - Identificadores e dependências.
   - Existência de ciclos.
   - Compatibilidade com ferramentas disponíveis.
   - Restrições de segurança e permissões.

   O modelo não pode simplesmente declarar que seu plano é válido.
4. **Decompor e executar**

   O núcleo organiza as etapas em subtarefas, respeitando suas dependências.

   Para cada subtarefa:
   1. Identifica a operação necessária.
   2. Seleciona uma ferramenta autorizada.
   3. Valida os argumentos.
   4. Executa a ferramenta.
   5. Registra o resultado e os efeitos produzidos.

   As operações podem envolver criação, leitura, modificação, exclusão, compilação e execução.
5. **Integrar os resultados**

   Depois das subtarefas, o ATOM verifica se os componentes produzidos funcionam em conjunto.

   Não basta cada arquivo estar correto individualmente: as dependências e interfaces também precisam ser compatíveis.
6. **Testar e verificar**

   O sistema executa verificações em diferentes níveis:
   - Sintaxe.
   - Tipagem.
   - Estrutura.
   - Semântica.
   - Integração.
   - Regressão.

   A conclusão precisa ser sustentada por evidências observáveis, não pela afirmação do modelo.
7. **Analisar erros e corrigir**

   Se houver falhas, o ATOM reúne os resultados, identifica possíveis causas e solicita correções.

   O processo retorna à execução das etapas necessárias, sem precisar reiniciar toda a tarefa.

   As tentativas devem ter limites definidos. Problemas externos ou impossibilidade de prosseguir podem colocar a tarefa em estado `BLOCKED`.
8. **Emitir relatório final**

   O ATOM apresenta:
   - O que foi solicitado.
   - O que foi executado.
   - Arquivos e componentes afetados.
   - Testes realizados.
   - Erros encontrados e correções aplicadas.
   - Critérios atendidos e pendências.

   Só declara a tarefa concluída quando os critérios de sucesso forem verificados.

## **3. A separação de responsabilidades**

Um dos pontos mais importantes da arquitetura foi não misturar análise, decisão e execução.

| Subsistema  | Responsabilidade                                           |
| ----------- | ---------------------------------------------------------- |
| Analisador  | Coletar fatos sobre o projeto e seu estado.                |
| Planejador  | Propor etapas e dependências com auxílio do Ollama.        |
| Validador   | Verificar contratos, regras, permissões e viabilidade.     |
| Registry    | Disponibilizar ferramentas conhecidas e autorizadas.       |
| Executor    | Executar operações e registrar resultados.                 |
| Verificador | Conferir se os resultados realmente atendem aos critérios. |
| Runtime     | Orquestrar o fluxo e controlar os estados da tarefa.       |

Essa separação evita que o modelo tenha autoridade irrestrita sobre o sistema.

## **4. O controle de estados**

Também definimos uma máquina de estados para acompanhar o ciclo de vida da tarefa:

CREATED

PLANNING

READY

RUNNING

**BLOCKED**

Aguardando condição externa ou intervenção.

**FAILED**

Execução sem sucesso.

**COMPLETED**

Critérios verificados.

**CANCELLED**

Tarefa interrompida.

Esses estados permitem distinguir situações que, em agentes mais simples, acabam sendo confundidas: plano elaborado, operação executada e resultado efetivamente verificado.

## **5. A ideia mais importante que surgiu dos nossos experimentos**

O teste incremental do Jogo da Vida de Conway nos mostrou algo importante: um modelo pode produzir funções individualmente corretas e ainda assim gerar problemas quando elas são integradas.

O exemplo foi uma simulação que deveria começar na geração zero, mas começou na geração quatro porque o estado compartilhado havia sido alterado por testes anteriores.

Isso reforçou nossa decisão de registrar mais do que nomes e assinaturas de funções. O ATOM precisa compreender também:

- Responsabilidades dos componentes.
- Dependências.
- Pré-condições e pós-condições.
- Invariantes.
- Efeitos colaterais de leitura e escrita.
- Estado atual dos artefatos.

Assim, o núcleo consegue verificar não apenas se o código parece correto, mas também se sua execução respeita o comportamento esperado do projeto.

## **Síntese da estratégia**

A arquitetura que estamos construindo pode ser resumida em uma divisão:

**A IA pensa e propõe. O núcleo analisa, valida e controla. As ferramentas executam. O verificador comprova.**

O objetivo não é criar um agente que dependa de um modelo cada vez maior para resolver tarefas complexas. É criar uma infraestrutura capaz de organizar o trabalho, preservar contexto relevante, controlar efeitos colaterais e verificar resultados — mesmo quando o modelo possui limitações de contexto ou raciocínio.

Essa é a essência técnica do ATOM: **transformar a capacidade generativa de um modelo em execução controlada e verificável.**&#x20;

# **Code Breaker**

O **Code Breaker** é o componente responsável por decompor unidades de trabalho complexas em unidades menores e, posteriormente, reconstruí-las em uma unidade coerente.

Sua finalidade dentro do ATOM é permitir que tarefas complexas sejam executadas de maneira distribuída, controlada e verificável, sem exigir que o modelo generativo mantenha todo o problema em seu contexto.

Sua estrutura possui dois componentes:

## **Code Breaker**

**Composer**

Decomposição

**Recomposer**

Reconstrução

## **1. Composer — decomposição**

O Composer recebe um `StepNode` e analisa se ele pode ser dividido em unidades menores de trabalho.

Por exemplo, considere a tarefa:

**Criar a classe&#x20;**`Snake.java`, contendo atributos, construtor e métodos de movimentação.

O Composer poderia dividi-la em:

- Node 1: criar a estrutura da classe, atributos e construtor.
- Node 2: implementar o método de movimentação.
- Node 3: implementar o método de crescimento.

Esses Nodes passam a representar responsabilidades menores, que podem ser executadas independentemente quando não houver dependências entre elas.

A decomposição pode ser recursiva: um Node filho também pode ser decomposto.

**Uma distinção importante:** a hierarquia entre pai e filhos não determina necessariamente dependências de execução. As dependências precisam ser representadas separadamente.

## **2. Recomposer — reconstrução**

O Recomposer trabalha no sentido inverso.

Ele recebe os resultados produzidos pelos Nodes filhos e os integra para reconstruir o resultado esperado pelo Node pai.

Entretanto, não basta concatenar os resultados.

Imagine que um Node filho produza os atributos e o construtor de `Snake.java`, enquanto outro produza o método `move()`.

O Recomposer precisa compreender que ambos pertencem à mesma classe e posicioná-los corretamente.

Para isso, concluímos que ele deve trabalhar com um **contrato de recomposição**.

Esse contrato pertence ao Node pai e descreve como os resultados dos filhos devem contribuir para o objetivo original.

Exemplo conceitual:

```
recomposition_contract = {    "artifact": "Snake.java",    "structure": "class",    "members": [        {"source_node": 1, "role": "attributes"},        {"source_node": 2, "role": "methods"},        {"source_node": 3, "role": "methods"}    ]}
```

O contrato não é a implementação da reconstrução: é a especificação que orienta o Recomposer.

## **3. Relação com StepNode**

O Code Breaker trabalha diretamente sobre a estrutura `StepNode`.

Até agora, definimos que ela mantém três dimensões independentes:

| Dimensão         | Responsabilidade                           |
| ---------------- | ------------------------------------------ |
| `plan`           | Descrição e objetivo original do trabalho. |
| `classification` | Operações identificadas para sua execução. |
| `state`          | Estado atual de execução.                  |

Além disso, um Node pode possuir filhos e um contrato de recomposição.

Estabelecemos também uma regra importante:

- Node sem filhos: pode ser executado diretamente.
- Node com filhos: sua execução é delegada aos filhos.
- Após os filhos terminarem: o resultado é integrado e o objetivo do pai é verificado.

Portanto, concluir todos os filhos não significa necessariamente concluir o pai.

## **4. Relação com o Validador**

O Validador é um componente distinto do Code Breaker, mas trabalha em conjunto com ele.

A divisão de responsabilidades é:

| Componente | Responsabilidade                                           |
| ---------- | ---------------------------------------------------------- |
| Composer   | Decompor o trabalho.                                       |
| Recomposer | Reconstruir o resultado.                                   |
| Validador  | Verificar se o resultado atende aos contratos e critérios. |

A validação pode envolver:

- **Estrutural:** os elementos esperados existem?
- **Sintática:** o código é válido?
- **Semântica:** os elementos possuem o comportamento esperado?
- **Integração:** os componentes funcionam corretamente em conjunto?
- **Contratual:** o objetivo original do Node foi satisfeito?

O Validador também pode ser utilizado em Nodes que nunca passaram por decomposição.

## **5. Como o Recomposer deve reconstruir?**

Uma conclusão importante das nossas discussões é que não devemos depender exclusivamente de um modelo generativo para reconstruir resultados.

Uma abordagem híbrida parece mais adequada:

1. O modelo analisa os resultados dos filhos e o contrato de recomposição.
2. O Recomposer organiza a reconstrução.
3. Ferramentas determinísticas, como ASTs e parsers, realizam operações estruturais quando aplicável.
4. O Validador verifica o resultado.

Por exemplo, em Java, um AST permite inserir um método dentro da classe correta sem depender de manipulação textual frágil.

Nem toda recomposição precisa de IA. Quando o contrato especifica precisamente como integrar os resultados, o processo pode ser determinístico.

## **6. Conclusão arquitetural**

O Code Breaker resolve um problema central do ATOM: **como executar tarefas complexas sem depender de uma única geração extensa do modelo?**

Ele permite dividir o trabalho, distribuir responsabilidades, executar partes independentes e reconstruir o resultado progressivamente.

O fluxo conceitual fica assim:

**StepNode pai**

Objetivo original e contrato

**Composer**

Decomposição em Nodes filhos

**Execução dos Nodes filhos**

Runtime e ferramentas autorizadas

**Recomposer**

Integração dos resultados

**Validador**

Verificação do objetivo original

StepNode concluído

**Minha avaliação:** a separação entre Composer, Recomposer e Validador é uma boa decisão arquitetural. Cada um resolve um problema diferente: dividir, integrar e verificar.
