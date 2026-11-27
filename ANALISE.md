# Diagnóstico do case de precatórios

O [diagnostico.py](diagnostico.py) lê os quatro arquivos de entrada e imprime as ocorrências com IDs de evento, linhas dos CSVs ou posições das apresentações. A amostra contém **13 registros de eventos, 11 IDs distintos, 6 apresentações e 4 processos em comum entre os CSVs**.

## Achados por gravidade

| Gravidade | Achado e evidência | Causa ou consequência e impacto |
|---|---|---|
| Crítica | **Reprocessamento e versões.** `pagamentos.json:3–8,67–72` traz duas versões de `ev-001` com R$ 15.000 e R$ 15.500. `pagamentos.json:11–16,27–32` repete `ev-002` sem mudança entre as ocorrências. `schema.sql:11` declara `evento_id` sem unicidade. | O enunciado descreve lotes de sete dias e reexecução após falhas. Somar cada ocorrência permite que as duplicatas e as versões inflem o total. Somar as duas versões de `ev-001` resulta em R$ 30.500. Se a última versão substituir a primeira, o valor vigente é R$ 15.500 e a atualização sobre o primeiro valor é de R$ 500. |
| Crítica | **Estorno e sinal.** Há 12 registros do tipo `pagamento` e 1 do tipo `estorno`. `ev-007` traz estorno de R$ 5.000 em `pagamentos.json:59–64`. `ev-009` é um pagamento de −R$ 200 em `pagamentos.json:83–88`. A amostra tem zero valores zerados. | `DOCUMENTACAO_TRIBUNAL.md:15` prevê apenas pagamento. `schema.sql:12–13` permite estorno e exige valor positivo. Se o importador simplesmente somar o estorno, o total pago aumenta. Se tentar gravar o pagamento negativo nesse esquema, a restrição rejeita o registro. O possível vínculo de `ev-007` com `ev-006` depende de confirmação. |
| Alta | **Prazos.** `hub.csv:2` e `hub.csv:6` registram 31/12/2027. O cálculo do enunciado resulta em 31/12/2026 para ambos ao interpretar o item 5 no fuso UTC−03. Veja a tabela abaixo. | Um prazo deslocado em um ano altera a prioridade operacional. Para o primeiro processo, a data de 02/04 já é civil. Para o segundo, o resultado depende do fuso de corte. A causa no código do hub é desconhecida. |
| Alta | **Divergências de cadastro e valor.** Nas linhas 3 dos CSVs, `0023456-21.2020.8.26.0053` tem R$ 30.000 no tribunal e R$ 31.000 no hub. Nas linhas 5, `0045678-43.2021.5.02.0011` está associado à União no tribunal e ao Município de Santos no hub. | São diferenças após o cruzamento por CNJ. A diferença de R$ 1.000 afeta o valor da carteira. A de ente afeta a atribuição da dívida. Na amostra, a fonte de referência para cada campo precisa ser confirmada. |
| Alta | **Cobertura e vínculo.** `ev-010`, de R$ 750, tem processo vazio em `pagamentos.json:91–96` e não pode ser associado. `ev-009` encontra seu processo só em `hub.csv:6`. `ev-011` encontra seu processo só em `tribunal.csv:6`. `ev-004` tem valor nulo em `pagamentos.json:35–40`. | Processo vazio impede atribuir o pagamento. Valor nulo impede apurar o montante. A ausência em apenas um CSV demonstra uma diferença de cobertura entre as duas listas. O fluxo descrito no enunciado pode deixar essas pendências invisíveis ao operador. |
| Alta | **Representação no banco.** `schema.sql:3` usa `CHAR(20)`, enquanto o CNJ pontuado de `tribunal.csv:2` tem 25 caracteres. | A forma de 20 algarismos cabe. Se a escrita usar a forma pontuada, o tamanho é incompatível. A comparação do script usa os 20 algarismos em memória, preservando os zeros à esquerda. |
| Média | **Leiaute divergente.** `tribunal.csv:1` usa ponto e vírgula e, nas linhas de dados, os valores têm vírgula decimal. A decodificação UTF-8 falha na posição 72 a partir de zero. `DOCUMENTACAO_TRIBUNAL.md:20,26` promete UTF-8, vírgula entre campos e ponto decimal. `pagamentos.json:13–14,29–30` contém também moeda em texto e data com barras. | Um leitor configurado pelo leiaute declarado pode falhar ou interpretar campos incorretamente. A leitura diagnóstica usou CP1252 após a falha de UTF-8. A codificação oficial e o momento em que o arquivo ganhou esse leiaute são desconhecidos. |
| Média | **Diferenças de apresentação.** `tribunal.csv:2` e `hub.csv:2` diferem em caixa e acentuação do ente. As linhas 3 apresentam o mesmo CNJ com e sem máscara. `ev-005`, em `pagamentos.json:43–44`, também aparece sem máscara e vincula aos dois CSVs. Nas linhas 2, 4 e 5 dos CSVs, o valor de face coincide após interpretar a notação decimal. | A comparação literal do fluxo trata diferenças de escrita como divergências de dados. O cruzamento usa a forma sem máscara e distingue diferenças de grafia, valor e ente. |

## Conferência das apresentações

O corte do enunciado inclui 2 de abril. Uma data sem horário é comparada como data civil. Para registros com horário, o diagnóstico usa UTC−03 como hipótese e extrai a data depois da conversão. `DOCUMENTACAO_TRIBUNAL.md` não especifica o leiaute de `apresentacoes.json`.

| Processo | Evidência em `apresentacoes.json` | Dia civil | Prazo calculado | Prazo no hub |
|---|---|---|---|---|
| `0012345-10.2019.8.26.0053` | Linha 4, `2025-04-02` | 02/04/2025 | 31/12/2026 | 31/12/2027, linha 2 |
| `0023456-21.2020.8.26.0053` | Linha 8, `2025-04-03` | 03/04/2025 | 31/12/2027 | 31/12/2027, linha 3 |
| `0034567-32.2018.8.26.0405` | Linha 12, `2024-02-29` | 29/02/2024 | 31/12/2025 | 31/12/2025, linha 4 |
| `0045678-43.2021.5.02.0011` | Linha 16, `2025-04-02T23:30:00-03:00` | 02/04/2025 | 31/12/2026 | 31/12/2026, linha 5 |
| `0056789-54.2017.4.03.6100` | Linha 20, `2025-04-03T01:00:00Z` | 02/04/2025 | 31/12/2026 | 31/12/2027, linha 6 |
| `0067890-65.2016.8.26.0053` | Linha 24, `2023-12-31` | 31/12/2023 | 31/12/2025 | Processo ausente no hub |

## Prevenção no processo e no importador

| Onde agir | Proposta | Problema que resolve |
|---|---|---|
| Recebimento | Arquivar os bytes originais com fonte, data de chegada e SHA-256, que identifica o conteúdo recebido. Tratar o Excel como visualização. Validar cabeçalho, versão, codificação, delimitador, campos obrigatórios e formato antes de importar. | Preserva evidência. Permite reconhecer o reenvio do mesmo arquivo e identificar mudanças no leiaute antes que afetem totais. |
| Preparação do lote | Registrar cada item com posição, original, normalizado e motivo. Validar CNJ como texto, preservar zeros, ler moeda com precisão decimal e interpretar datas com calendário e fuso explícitos. Arquivo ilegível interrompe o lote. Registros isolados inadequados entram em fila de revisão. | Evita perda silenciosa e impede que conversões fabriquem centavos, datas ou processos. Cada pendência tem uma referência para correção. |
| Identidade e versões | Usar a chave do lote para retries exatos e a chave do evento para sobreposições de janelas. Agrupar antes de gravar. Conservar as versões brutas, aceitar apenas atualização compatível com timestamp mais recente e registrar empates divergentes para revisão. | Um novo arquivo pode repetir eventos de um arquivo anterior. Um hash do lote sozinho cobre apenas reenvio idêntico. |
| Banco e falha parcial | Validar fora da transação de escrita. Dentro dela, bloquear o lote, gravar os eventos com UPSERT e confirmar a auditoria e o estado do lote conjuntamente. Em erro inesperado, reverter e registrar a falha em outra transação. Retentar falhas transitórias sem liberar versões duvidosas. | Evita aplicar metade do lote e evita que dois importadores simultâneos dupliquem um evento ou que a versão antiga sobrescreva a nova. |
| Financeiro e cadastro | Consultar pagamentos vigentes em vez de incrementar um saldo a cada recebimento. Vincular pagamentos ao cadastro por chave estrangeira. Em cruzamentos semanais, publicar diferenças de cobertura, ente, valor, formatos e prazo. Tratar estornos e conflitos com confirmação humana. | Evita contar as mesmas versões duas vezes e evita escolher silenciosamente uma das fontes. Uma restrição de vínculo também bloqueia referências sem cadastro. |
| Operação | Medir lidos, aplicados, duplicatas, substituições, pendências, falhas e tempo de conclusão por lote. Alertar sobre arquivo inválido, empate divergente, aumento de rejeições e lote que não chegou ou não concluiu. Identificar responsável por resolver a fila, sem enviar registros completos nos alertas. | A operação passa a distinguir falha de chegada, falha técnica e divergência de dados. Os indicadores podem ser conferidos com os registros do lote. |

## Proposta para o banco

O [melhorias.sql](melhorias.sql) propõe uma migração PostgreSQL. O esquema original já tem chave estrangeira de pagamento para precatório, unicidade do processo, `NUMERIC(15,2)`, tipo limitado e valor positivo. Faltam unicidade do evento, verificação da forma canônica do CNJ, referência ao lote de origem e timestamp da fonte. `criado_em` registra a criação no banco e tem outra finalidade. O índice em `pagamento.precatorio_id` apoia as buscas por processo e o uso da chave estrangeira.

A migração checa duplicatas e cadastros incompatíveis antes de criar restrições. Se encontrar problemas, interrompe a transação. O plano é reconciliar e arquivar o legado com evidência antes de tentar de novo. Timestamps de origem e referências de lote desconhecidos permanecem nulos no legado até recuperação comprovada. A restrição `NOT VALID` já exige esses campos nas novas escritas e permite validar o acervo depois do preenchimento.

O UPSERT usa o evento único e só altera valor, timestamp e lote da versão vigente quando a entrada é mais recente e tem processo, tipo e data compatíveis. A auditoria guarda o original e o estado da importação. A função compara com a versão vigente. Empates de versões no arquivo e divergências de histórico entre lotes devem ser investigados na preparação e na conciliação. Antes de migrar em produção, confirme o escopo do identificador, a janela para bloqueios, as permissões do importador e a capacidade de reconciliar o saldo antigo. O limite de duas casas e 13 dígitos inteiros é conferido antes de gravar para evitar arredondamento implícito.

Referências técnicas: [UPSERT no PostgreSQL](https://www.postgresql.org/docs/18/sql-insert.html), [restrições no PostgreSQL](https://www.postgresql.org/docs/18/sql-altertable.html).

## Perguntas para confirmar com a operação

- O ID do evento é único em qual escopo? Um `atualizado_em` mais recente substitui integralmente o registro anterior?
- Como resolver duas versões no mesmo instante? Existe número de versão ou identificador de correção no tribunal?
- Como o tribunal identifica o pagamento associado a um estorno? O que significa um pagamento com valor negativo ou zero?
- Qual fuso define o dia do corte? O que uma data de apresentação sem horário representa no arquivo?
- Qual fonte prevalece por campo e quais filtros explicam a presença de um processo em apenas um CSV?
- Quais são a codificação, o separador de campo, o formato monetário e as variantes oficiais do CNJ em cada arquivo?

## Validação executada

O diagnóstico rodou com Python 3.14.2 a partir de duas pastas e produziu a mesma saída. Em cópias temporárias, foram conferidos valor zero, tipo desconhecido, valor negativo em texto, processo ausente nos dois CSVs, data de pagamento nula e apresentação com horário sem fuso. A sintaxe foi conferida no modo Python 3.10. A execução foi feita com o interpretador 3.14.2 disponível na máquina.

A limpeza da amostra produziu 4 identidades de processo, das quais 2 têm campos cadastrais pendentes, e 6 pagamentos. O relatório contabiliza **29 registros de entrada**, com 13 corrigidos, 2 descartados (cópia e versão anterior) e 14 pendentes. A soma descreve linhas de origem. Os 4 processos da base resultam da combinação de pares dos CSVs.

No PostgreSQL 18 temporário, a migração foi executada sobre o esquema de origem. Foram conferidos o registro de auditoria, a atualização de um evento, o retry, a rejeição de precisão excessiva, o tratamento de zeros e estornos, o empate de versões e o rollback de uma importação. A verificação ocorreu em sessão única. A concorrência entre importadores e a migração do acervo real ficam para homologação.

Em outro cenário temporário, duas linhas legadas com o mesmo ID abortaram a migração. As duas linhas foram preservadas e as novas tabelas ficaram ausentes após o rollback.
