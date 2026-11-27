# Conciliação de precatórios

Case técnico que diagnostica diferenças entre os arquivos do tribunal e do hub e gera uma base conciliada com rastreabilidade por registro.

## Como executar

Requer Python 3.10 ou posterior. O código usa a biblioteca padrão e os comandos partem da pasta do projeto.

```shell
python diagnostico.py
python limpeza.py
python -m unittest discover -s tests -v
```

O diagnóstico imprime evidências no terminal. A limpeza lê `dados/` e grava em `saida/`. Para definir outras pastas, use `python limpeza.py --dados caminho/entrada --saida caminho/resultado`.

## Arquivos principais

| Arquivo | Finalidade |
|---|---|
| `dados/`, `DOCUMENTACAO_TRIBUNAL.md` e `schema.sql` | Entradas, leiaute recebido e esquema original |
| `diagnostico.py` e `ANALISE.md` | Diagnóstico, evidências, prevenção e perguntas à operação |
| `limpeza.py` e `regras.py` | Limpeza, conciliação e regras que o diagnóstico também usa |
| `melhorias.sql` | Proposta de migração PostgreSQL, com checagem de dados legados |
| `tests/` | Testes unitários e de integração com arquivos temporários |
| `saida/base_limpa.json` | Processos identificados nas duas fontes, campos conciliados e pagamentos selecionados |
| `saida/relatorio_limpeza.json` | Layouts detectados, indicadores, hipóteses e decisão por registro com original e alterações |

No relatório, `posicao` indica a linha inicial do CSV ou o item do JSON, começando em 1. Números fracionários originais do JSON usam a representação `{"numero_json_decimal": "..."}` para preservar sua precisão e distingui-los de texto. A base representa dinheiro normalizado como texto com duas casas decimais.

## Decisões e limites

- O CNJ é uma string de 20 algarismos. Campos cadastrais conflitantes ficam no relatório. A base pode identificar um processo nas duas fontes e manter algum atributo pendente.
- Uma versão mais recente substitui a anterior se as versões forem válidas, tenham o mesmo processo, tipo e data de pagamento e não empatem no timestamp. Estornos, vínculos com apenas uma fonte e dados insuficientes ficam pendentes. O formato localizado de data usa dia/mês/ano.
- A data civil de 2 de abril entra no corte. UTC−03 serve de cenário para apresentações com horário. Esses prazos ficam pendentes de confirmação do fuso. A base contém pagamentos selecionados, com pendências em aberto que impedem interpretar o conjunto como saldo líquido da carteira.
- A saída é determinística para as mesmas entradas. Cada JSON é substituído de forma atômica. Em falha entre as duas gravações, execute novamente antes de usar os resultados juntos.

## Validação e uso de IA

ChatGPT e Codex apoiaram o estudo do case, a investigação dos dados, a implementação, a documentação e os testes. A conferência executada compara as saídas com os dados originais, inclui testes automatizados e verifica que reprocessar o mesmo lote gera os mesmos arquivos. A confirmação das hipóteses de negócio e a revisão da migração em homologação dependem da operação.

Foram executados 13 testes em Python 3.14.2. A sintaxe foi conferida para 3.10. O SQL foi exercitado em PostgreSQL 18 temporário, em sessão única. A execução concorrente e a migração com o acervo real precisam de validação em homologação.
