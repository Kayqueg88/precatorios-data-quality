import csv
import json
from collections import Counter, defaultdict
from io import StringIO
from pathlib import Path

from regras import CNJ_FORMATADO, DATA_ISO, chave_cnj, chave_ente, data_pagamento, prazo_da_apresentacao, valor_decimal


BASE_DIR = Path(__file__).resolve().parent
DADOS = BASE_DIR / "dados"


def ler_csv(nome, coluna_processo, delimitador_previsto):
    conteudo = (DADOS / nome).read_bytes()
    try:
        texto = conteudo.decode("utf-8-sig")
    except UnicodeDecodeError as erro:
        if nome != "tribunal.csv":
            raise
        texto = conteudo.decode("cp1252")
        print(f"{nome}: UTF-8 falhou no byte de posição {erro.start}. Leitura com CP1252.")

    registros = {}
    repetidos = set()
    with StringIO(texto, newline="") as arquivo:
        cabecalho = arquivo.readline()
        delimitador = csv.Sniffer().sniff(cabecalho, delimiters=",;").delimiter
        arquivo.seek(0)
        if delimitador != delimitador_previsto:
            print(f"{nome}: delimitador {delimitador!r}, previsto {delimitador_previsto!r}.")
        leitor = csv.DictReader(arquivo, delimiter=delimitador)
        for registro in leitor:
            processo = registro.get(coluna_processo)
            chave = chave_cnj(processo)
            origem = f"{nome}:{leitor.line_num}"
            if chave is None:
                print(f"{origem}: processo sem chave CNJ utilizável: {processo!r}")
            elif chave in registros:
                primeira_origem, _ = registros[chave]
                print(f"{origem}: CNJ repetido {processo!r} (primeira ocorrência em {primeira_origem}).")
                repetidos.add(chave)
            else:
                registros[chave] = origem, registro
    return registros, repetidos


def main():
    with (DADOS / "pagamentos.json").open(encoding="utf-8") as arquivo:
        pagamentos = json.load(arquivo)

    print("Total de registros:", len(pagamentos))

    grupos = defaultdict(list)
    for pagamento in pagamentos:
        grupos[pagamento["evento_id"]].append(pagamento)

    print("IDs únicos:", len(grupos))
    print("\nRegistros com IDs repetidos:")
    for evento_id, grupo in grupos.items():
        if len(grupo) == 1:
            continue
        distintos = []
        for pagamento in grupo:
            if pagamento not in distintos:
                distintos.append(pagamento)
            print(pagamento)
        if len(distintos) < len(grupo):
            print(f"  {evento_id}: {len(grupo) - len(distintos)} cópia(s) idêntica(s).")
        if len(distintos) > 1:
            print(f"  {evento_id}: {len(distintos)} versões ou registros conflitantes.")
    print("  Risco no fluxo do enunciado: janela de 7 dias e reexecução podem repetir eventos.")

    print("\nValores fora do padrão:")

    for pagamento in pagamentos:

        valor = pagamento.get("valor")
        if type(valor) not in (float, int) or valor_decimal(valor) is None:
            print(pagamento)


    for pagamento in pagamentos:
        try:
            texto = pagamento.get("data_pagamento")
            if not isinstance(texto, str) or not DATA_ISO.fullmatch(texto):
                raise ValueError("O leiaute declara AAAA-MM-DD.")
            data_pagamento(texto)
        except ValueError:
            print("\nData fora do padrão:", pagamento)


    for pagamento in pagamentos:

        processo = pagamento.get("processo")
        if not isinstance(processo, str) or not CNJ_FORMATADO.fullmatch(processo):
            print("\nProcessos fora do padrão CNJ:", pagamento)


    print("\nTipos de evento e valores não positivos:")
    tipos = Counter(str(pagamento.get("tipo")) for pagamento in pagamentos)
    for tipo, quantidade in sorted(tipos.items()):
        print(f"  {tipo}: {quantidade} registro(s)")

    negativos = zerados = 0
    for pagamento in pagamentos:
        evento_id = pagamento["evento_id"]
        tipo = pagamento.get("tipo")
        if tipo == "estorno":
            print(f"  {evento_id}: estorno previsto no schema.sql, ausente no leiaute do tribunal.")
        elif tipo != "pagamento":
            print(f"  {evento_id}: tipo de evento desconhecido: {tipo!r}")

        valor = valor_decimal(pagamento.get("valor"))
        if valor is not None and valor < 0:
            negativos += 1
            print(f"  {evento_id}: valor negativo {valor} ({tipo!r}).")
        elif valor == 0:
            zerados += 1
            print(f"  {evento_id}: valor zerado ({tipo!r}).")
    print(f"  Negativos: {negativos} | Zerados: {zerados}")


    print("\nLeitura e comparação dos CSVs:")
    tribunal, repetidos_tribunal = ler_csv("tribunal.csv", "numero_processo", ",")
    hub, repetidos_hub = ler_csv("hub.csv", "processo", ",")
    comuns = tribunal.keys() & hub.keys()
    so_tribunal = tribunal.keys() - hub.keys()
    so_hub = hub.keys() - tribunal.keys()
    print(f"  Em comum: {len(comuns)} | Só no tribunal: {len(so_tribunal)} | Só no hub: {len(so_hub)}")

    for indice, chaves, coluna, fonte in (
        (tribunal, so_tribunal, "numero_processo", "tribunal"),
        (hub, so_hub, "processo", "hub"),
    ):
        for chave in sorted(chaves):
            origem, registro = indice[chave]
            print(f"  {origem}: processo só no {fonte}: {registro[coluna]}")

    for chave in sorted(comuns - repetidos_tribunal - repetidos_hub):
        origem_tribunal, registro_tribunal = tribunal[chave]
        origem_hub, registro_hub = hub[chave]
        processo = registro_tribunal["numero_processo"]
        prefixo = f"  {processo} ({origem_tribunal} x {origem_hub})"
        if processo != registro_hub["processo"]:
            print(f"{prefixo}: formatação do CNJ: {processo!r} x {registro_hub['processo']!r}")

        ente_tribunal = registro_tribunal["ente_devedor"] or ""
        ente_hub = registro_hub["ente"] or ""
        if not ente_tribunal.strip() or not ente_hub.strip():
            print(f"{prefixo}: ente ausente: {ente_tribunal!r} x {ente_hub!r}")
        elif ente_tribunal != ente_hub:
            motivo = "formatação do ente" if chave_ente(ente_tribunal) == chave_ente(ente_hub) else "divergência cadastral (ente)"
            print(f"{prefixo}: {motivo}: {ente_tribunal!r} x {ente_hub!r}")

        valor_tribunal = registro_tribunal["valor_face"]
        valor_hub = registro_hub["valor_face"]
        decimal_tribunal = valor_decimal(valor_tribunal)
        decimal_hub = valor_decimal(valor_hub)
        if decimal_tribunal is None or decimal_hub is None:
            print(f"{prefixo}: valor de face ilegível: {valor_tribunal!r} x {valor_hub!r}")
        elif decimal_tribunal != decimal_hub:
            diferenca = decimal_hub - decimal_tribunal
            print(f"{prefixo}: divergência financeira (valor de face): "
                  f"{valor_tribunal!r} x {valor_hub!r} (hub - tribunal: R$ {diferenca:+.2f})")
        elif valor_tribunal != valor_hub:
            print(f"{prefixo}: formatação do valor de face: {valor_tribunal!r} x {valor_hub!r}")


    print("\nCorrespondência dos pagamentos com os CSVs:")
    sem_correspondencia = 0
    for pagamento in pagamentos:
        processo = pagamento.get("processo")
        chave = chave_cnj(processo)
        evento_id = pagamento["evento_id"]
        if chave is None:
            sem_correspondencia += 1
            print(f"  {evento_id}: sem correspondência, processo vazio ou inválido: {processo!r}")
        elif chave not in tribunal and chave not in hub:
            sem_correspondencia += 1
            print(f"  {evento_id}: sem correspondência em ambos os CSVs: {processo}")
        elif chave not in tribunal:
            print(f"  {evento_id}: processo {processo} encontrado apenas no hub.")
        elif chave not in hub:
            print(f"  {evento_id}: processo {processo} encontrado apenas no tribunal.")
    print(f"  Registros sem correspondência: {sem_correspondencia}")


    print("\nApresentações e prazos (UTC-03:00 para registros com horário):")
    with (DADOS / "apresentacoes.json").open(encoding="utf-8") as arquivo:
        apresentacoes = json.load(arquivo)

    divergencias = 0
    for posicao, apresentacao in enumerate(apresentacoes, start=1):
        processo = apresentacao.get("processo")
        apresentado_em = apresentacao.get("apresentado_em")
        chave = chave_cnj(processo)
        prefixo = f"  apresentacoes.json item {posicao} ({processo!r})"
        if chave is None:
            print(f"{prefixo}: processo inválido para cruzamento.")
            continue
        try:
            if not isinstance(apresentado_em, str):
                raise ValueError("data de apresentação ausente ou não textual")
            dia, prazo = prazo_da_apresentacao(apresentado_em)
        except ValueError as erro:
            print(f"{prefixo}: apresentação inválida {apresentado_em!r} ({erro}).")
            continue

        evidencia = f"{prefixo}: {apresentado_em} | dia civil {dia} | prazo esperado {prazo}"
        if chave not in hub:
            print(f"{evidencia} | processo ausente no hub")
        elif chave in repetidos_hub:
            print(f"{evidencia} | comparação ambígua, CNJ repetido no hub")
        else:
            origem, registro = hub[chave]
            prazo_hub = registro["prazo_pagamento"]
            if prazo_hub != prazo.isoformat():
                divergencias += 1
                print(f"{evidencia} | {origem}: prazo divergente {prazo_hub!r}")
            else:
                print(f"{evidencia} | {origem}: prazo confere")
    print(f"  Prazos divergentes no hub: {divergencias}")


if __name__ == "__main__":
    main()
