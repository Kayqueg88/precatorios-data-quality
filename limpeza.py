"""Gera uma base conciliada e registra o tratamento de cada linha de origem."""

import argparse
import csv
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import timezone
from decimal import Decimal
from io import StringIO
from pathlib import Path
from tempfile import NamedTemporaryFile

from regras import DATA_ISO, chave_cnj, chave_ente, data_pagamento, instante_iso, prazo_da_apresentacao, valor_decimal


RAIZ = Path(__file__).resolve().parent
SITUACOES = ("aceito", "corrigido", "descartado", "pendente")


@dataclass
class Registro:
    arquivo: str
    posicao: int
    original: object
    normalizado: dict = field(default_factory=dict)
    alteracoes: dict = field(default_factory=dict)
    motivos: list = field(default_factory=list)
    situacao: str = ""
    comparacao: dict = field(default_factory=dict)

    def guardar(self, campo, valor, campo_origem=None):
        campo_origem = campo_origem or campo
        self.normalizado[campo] = valor
        anterior = self.original.get(campo_origem)
        if anterior != valor:
            self.alteracoes[campo] = {"campo_origem": campo_origem, "antes": anterior, "depois": valor}

    def pendencia(self, motivo):
        self.situacao = "pendente"
        self.motivos.append(motivo)

    def concluir(self):
        if not self.situacao:
            self.situacao = "corrigido" if self.alteracoes else "aceito"
            if self.alteracoes:
                self.motivos.append("Padronização dos campos indicados em alteracoes.")


def representar_decimal(valor):
    if isinstance(valor, Decimal):
        return {"numero_json_decimal": str(valor)}
    raise TypeError(f"Tipo indisponível na saída JSON: {type(valor).__name__}")


def carregar_json(pasta, nome):
    def objeto_sem_chaves_repetidas(pares):
        objeto = dict(pares)
        if len(objeto) != len(pares):
            raise ValueError("objeto JSON com campo repetido")
        return objeto

    def constante_invalida(texto):
        raise ValueError(f"constante fora do padrão JSON: {texto}")

    try:
        texto = (pasta / nome).read_text(encoding="utf-8-sig")
        itens = json.loads(texto, parse_float=Decimal, parse_constant=constante_invalida,
                           object_pairs_hook=objeto_sem_chaves_repetidas)
    except (UnicodeError, ValueError) as erro:
        raise ValueError(f"{nome}: {erro}") from erro
    if not isinstance(itens, list):
        raise ValueError(f"{nome}: esperava uma lista de registros.")
    return [Registro(nome, i, item) for i, item in enumerate(itens, 1)]


def carregar_csv(pasta, nome, colunas):
    bruto = (pasta / nome).read_bytes()
    codificacao = "utf-8-sig"
    rejeicao_utf8 = None
    try:
        texto = bruto.decode(codificacao)
    except UnicodeDecodeError as erro:
        if nome != "tribunal.csv":
            raise ValueError(f"{nome}: UTF-8 inválido na posição {erro.start}.") from erro
        rejeicao_utf8 = erro.start
        codificacao = "cp1252"
        try:
            texto = bruto.decode(codificacao)
        except UnicodeDecodeError as erro:
            raise ValueError(f"{nome}: falha também na leitura CP1252.") from erro

    registros = []
    try:
        with StringIO(texto, newline="") as arquivo:
            delimitador = csv.Sniffer().sniff(arquivo.readline(), delimiters=",;").delimiter
            arquivo.seek(0)
            leitor = csv.reader(arquivo, delimiter=delimitador, strict=True)
            cabecalho = next(leitor, [])
            if len(set(cabecalho)) != len(cabecalho) or not set(colunas).issubset(cabecalho):
                raise ValueError(f"{nome}: cabeçalho ausente, incompleto ou com colunas repetidas.")
            linha = leitor.line_num + 1
            for valores in leitor:
                original = dict(zip(cabecalho, valores))
                registro = Registro(nome, linha, original)
                linha = leitor.line_num + 1
                if len(valores) != len(cabecalho):
                    registro.comparacao["celulas_originais"] = valores
                    registro.pendencia("Quantidade de campos diferente do cabeçalho.")
                registros.append(registro)
    except csv.Error as erro:
        raise ValueError(f"{nome}: CSV ilegível ({erro}).") from erro
    return registros, {"codificacao_leitura": codificacao, "delimitador": delimitador,
                       "posicao_falha_utf8": rejeicao_utf8}


def dinheiro_positivo(registro, campo):
    valor = valor_decimal(registro.original.get(campo))
    if valor is None:
        registro.pendencia(f"{campo}: valor ausente ou formato monetário inválido.")
    elif valor < 0:
        registro.pendencia(f"{campo}: valor negativo, confirmar o significado.")
    elif valor == 0:
        registro.pendencia(f"{campo}: valor zerado, confirmar o significado.")
    elif valor >= Decimal("10000000000000") or valor != valor.quantize(Decimal("0.01")):
        registro.pendencia(f"{campo}: fora da precisão de NUMERIC(15,2) sem arredondamento.")
    else:
        registro.guardar(campo, f"{valor:.2f}")


def guardar_cnj(registro, campo):
    chave = chave_cnj(registro.original.get(campo))
    if chave is None:
        registro.pendencia("Processo ausente ou sem CNJ reconhecível.")
    else:
        registro.guardar("processo", chave, campo)


def agrupar(registros, campo):
    grupos = defaultdict(list)
    for registro in registros:
        chave = registro.normalizado.get(campo)
        if chave is not None:
            grupos[chave].append(registro)
    return grupos


def preparar_cadastros(registros, campo_cnj, campo_ente):
    for registro in registros:
        guardar_cnj(registro, campo_cnj)
        ente = registro.original.get(campo_ente, "").strip()
        if ente:
            registro.guardar("ente_devedor", ente, campo_ente)
        else:
            registro.pendencia("Ente devedor ausente.")
        dinheiro_positivo(registro, "valor_face")
    return agrupar(registros, "processo")


def conciliar_cadastros(tribunal, hub):
    processos = {}
    for chave in sorted(tribunal.keys() | hub.keys()):
        linhas_tribunal = tribunal.get(chave, [])
        linhas_hub = hub.get(chave, [])
        linhas = linhas_tribunal + linhas_hub
        if len(linhas_tribunal) != 1 or len(linhas_hub) != 1:
            motivo = ("CNJ com múltiplos cadastros em pelo menos uma fonte."
                      if len(linhas_tribunal) > 1 or len(linhas_hub) > 1
                      else "Processo presente em apenas uma fonte cadastral.")
            for linha in linhas:
                linha.pendencia(motivo)
            continue

        processo = {"processo": chave}
        origem_tribunal, origem_hub = linhas
        for campo in ("ente_devedor", "valor_face"):
            valor_tribunal = origem_tribunal.normalizado.get(campo)
            valor_hub = origem_hub.normalizado.get(campo)
            if campo == "ente_devedor" and valor_tribunal and valor_hub:
                coincide = chave_ente(valor_tribunal) == chave_ente(valor_hub)
            else:
                coincide = valor_tribunal is not None and valor_tribunal == valor_hub
            if coincide:
                processo[campo] = valor_tribunal
            else:
                for linha in linhas:
                    linha.comparacao[campo] = {"tribunal": valor_tribunal, "hub": valor_hub}
                    linha.pendencia(f"Campo {campo} divergente ou incompleto entre tribunal e hub.")
        processo["situacao_cadastro"] = (
            "pendente" if any(linha.situacao == "pendente" for linha in linhas) else "conciliado"
        )
        processos[chave] = processo
    return processos


def descartar_repeticoes(grupo):
    unicos = []
    vistos = {}
    for registro in grupo:
        assinatura = json.dumps(registro.original, sort_keys=True, default=representar_decimal)
        if assinatura in vistos:
            registro.situacao = "descartado"
            registro.motivos.append(f"Duplicata idêntica do item {vistos[assinatura].posicao}.")
        else:
            vistos[assinatura] = registro
            unicos.append(registro)
    return unicos


def preparar_eventos(registros, processos, chaves_cadastrais):
    for registro in registros:
        if not isinstance(registro.original, dict):
            registro.pendencia("Registro de pagamento não é um objeto JSON.")
            continue
        evento = registro.original
        evento_id = evento.get("evento_id")
        if isinstance(evento_id, str) and evento_id.strip() and evento_id == evento_id.strip():
            registro.guardar("evento_id", evento_id)
        else:
            registro.pendencia("ID do evento ausente ou inválido para agrupar versões.")
        guardar_cnj(registro, "processo")
        chave = registro.normalizado.get("processo")
        if chave is not None and chave not in processos:
            motivo = ("Processo sem cadastro nos CSVs." if chave not in chaves_cadastrais
                      else "Vínculo cadastral sem confirmação nas duas fontes.")
            registro.pendencia(motivo)

        tipo = evento.get("tipo")
        if tipo == "pagamento":
            registro.guardar("tipo", tipo)
        elif tipo == "estorno":
            registro.guardar("tipo", tipo)
            registro.pendencia("Estorno depende da regra de sinal e da referência ao pagamento original.")
        else:
            registro.pendencia("Tipo de evento desconhecido.")
        dinheiro_positivo(registro, "valor")
        try:
            registro.guardar("data_pagamento", data_pagamento(evento.get("data_pagamento")).isoformat())
        except ValueError as erro:
            registro.pendencia(f"Data de pagamento inválida ({erro}).")
        try:
            instante = instante_iso(evento.get("atualizado_em")).astimezone(timezone.utc)
            registro.guardar("atualizado_em", instante.isoformat())
        except (ValueError, OverflowError) as erro:
            registro.pendencia(f"Horário de atualização inválido ({erro}).")
    return agrupar(registros, "evento_id")


def selecionar_eventos(grupos):
    selecionados = []
    for evento_id in sorted(grupos):
        grupo = descartar_repeticoes(grupos[evento_id])
        motivo = None
        if any(r.situacao == "pendente" for r in grupo):
            motivo = "O evento tem versão pendente. A seleção fica em revisão."
        elif len({r.normalizado["atualizado_em"] for r in grupo}) < len(grupo):
            motivo = "Versões diferentes com o mesmo instante de atualização."
        elif len({(r.normalizado["processo"], r.normalizado["tipo"], r.normalizado["data_pagamento"])
                  for r in grupo}) > 1:
            motivo = "Versões divergem em processo, tipo ou data de pagamento."
        if motivo:
            for registro in grupo:
                registro.pendencia(motivo)
            continue

        vigente = max(grupo, key=lambda r: instante_iso(r.normalizado["atualizado_em"]))
        if len(grupo) > 1:
            vigente.motivos.append("Última versão válida selecionada pela hipótese de atualizado_em.")
        for registro in grupo:
            if registro is not vigente:
                registro.situacao = "descartado"
                registro.motivos.append(f"Versão anterior substituída pelo item {vigente.posicao}.")
        selecionados.append(vigente.normalizado)
    return selecionados


def conciliar_apresentacoes(registros, processos, hub):
    for registro in registros:
        if not isinstance(registro.original, dict):
            registro.pendencia("Registro de apresentação não é um objeto JSON.")
            continue
        guardar_cnj(registro, "processo")
        valor = registro.original.get("apresentado_em")
        try:
            dia, prazo = prazo_da_apresentacao(valor)
        except (ValueError, OverflowError) as erro:
            registro.pendencia(f"Apresentação inválida ({erro}).")
            continue
        registro.guardar("apresentado_em", dia.isoformat())
        registro.guardar("prazo_pagamento", prazo.isoformat())
        if not DATA_ISO.fullmatch(valor):
            registro.pendencia("Prazo calculado sob hipótese UTC-03:00. Confirmar fuso oficial.")

    for chave, grupo in agrupar(registros, "processo").items():
        unicos = descartar_repeticoes(grupo)
        if len(unicos) > 1:
            for registro in unicos:
                registro.pendencia("Apresentações diferentes para o mesmo processo.")
            continue

        registro = unicos[0]
        prazo = registro.normalizado.get("prazo_pagamento")
        linhas_hub = hub.get(chave, [])
        if prazo is not None and len(linhas_hub) == 1:
            linha_hub = linhas_hub[0]
            prazo_hub = linha_hub.original.get("prazo_pagamento")
            registro.comparacao["prazo_hub"] = {"linha": linha_hub.posicao, "valor": prazo_hub}
            if prazo_hub != prazo:
                registro.motivos.append("Prazo calculado diverge do registrado no hub.")
            data_hub = linha_hub.original.get("apresentado_em")
            try:
                dia_hub, _ = prazo_da_apresentacao(data_hub)
            except (ValueError, OverflowError):
                registro.pendencia("Data de apresentação ausente ou inválida no hub.")
            else:
                if dia_hub.isoformat() != registro.normalizado.get("apresentado_em"):
                    registro.comparacao["apresentado_em_hub"] = data_hub
                    registro.pendencia("Dia de apresentação diverge do hub.")
                elif not DATA_ISO.fullmatch(data_hub):
                    registro.pendencia("Dia de apresentação do hub depende do fuso oficial.")
        if chave not in processos:
            registro.pendencia("Apresentação sem cadastro confirmado nas duas fontes.")
        elif registro.situacao != "pendente":
            processos[chave]["apresentado_em"] = registro.normalizado["apresentado_em"]
            processos[chave]["prazo_pagamento"] = prazo


def montar_resultados(dados):
    pagamentos = carregar_json(dados, "pagamentos.json")
    apresentacoes = carregar_json(dados, "apresentacoes.json")
    linhas_tribunal, leiaute_tribunal = carregar_csv(
        dados, "tribunal.csv", ("numero_processo", "ente_devedor", "valor_face")
    )
    linhas_hub, leiaute_hub = carregar_csv(
        dados, "hub.csv", ("processo", "ente", "valor_face", "apresentado_em", "prazo_pagamento")
    )
    tribunal = preparar_cadastros(linhas_tribunal, "numero_processo", "ente_devedor")
    hub = preparar_cadastros(linhas_hub, "processo", "ente")
    processos = conciliar_cadastros(tribunal, hub)
    conciliar_apresentacoes(apresentacoes, processos, hub)
    eventos = preparar_eventos(pagamentos, processos, tribunal.keys() | hub.keys())
    selecionados = selecionar_eventos(eventos)
    base = {"processos": list(processos.values()), "pagamentos": selecionados}

    registros = pagamentos + apresentacoes + linhas_tribunal + linhas_hub
    por_arquivo = {}
    for registro in registros:
        registro.concluir()
        contagens = por_arquivo.setdefault(registro.arquivo, dict.fromkeys(SITUACOES, 0))
        contagens[registro.situacao] += 1
    totais = Counter(registro.situacao for registro in registros)
    relatorio = {
        "indicadores": {
            "registros_lidos": len(registros),
            "por_situacao": {situacao: totais[situacao] for situacao in SITUACOES},
            "por_arquivo": por_arquivo,
            "processos_na_base": len(processos),
            "processos_com_cadastro_pendente": sum(p["situacao_cadastro"] == "pendente" for p in processos.values()),
            "pagamentos_na_base": len(selecionados),
            "cnjs_em_comum": len(tribunal.keys() & hub.keys()),
            "cnjs_so_no_tribunal": len(tribunal.keys() - hub.keys()),
            "cnjs_so_no_hub": len(hub.keys() - tribunal.keys()),
        },
        "leiautes_csv": {"tribunal.csv": leiaute_tribunal, "hub.csv": leiaute_hub},
        "hipoteses": [
            "Pagamento localizado com barras usa dia/mês/ano.",
            "Atualizado_em elege a versão vigente se todas forem válidas, mantiverem processo, tipo e data, e não houver empate.",
            "CNJ confirma vínculo se aparecer uma vez em cada cadastro. Campos conflitantes ficam fora da base.",
            "UTC-03:00 é cenário para apresentações com horário. Esses prazos ficam pendentes.",
            "Estornos aguardam definição de sinal e vínculo com o pagamento original.",
        ],
        "registros": [asdict(registro) for registro in registros],
    }
    return base, relatorio


def executar(dados, saida):
    dados, saida = dados.resolve(), saida.resolve()
    if saida == dados or dados in saida.parents:
        raise ValueError("A pasta de saída deve ficar fora da pasta de dados originais.")
    base, relatorio = montar_resultados(dados)
    saida.mkdir(parents=True, exist_ok=True)
    for nome, resultado in (("base_limpa.json", base), ("relatorio_limpeza.json", relatorio)):
        conteudo = json.dumps(resultado, ensure_ascii=False, indent=2, default=representar_decimal) + "\n"
        destino = saida / nome
        arquivo = NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=saida, delete=False)
        temporario = Path(arquivo.name)
        try:
            with arquivo:
                arquivo.write(conteudo)
            temporario.replace(destino)
        finally:
            temporario.unlink(missing_ok=True)
    return relatorio["indicadores"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dados", type=Path, default=RAIZ / "dados")
    parser.add_argument("--saida", type=Path, default=RAIZ / "saida")
    argumentos = parser.parse_args()
    try:
        indicadores = executar(argumentos.dados, argumentos.saida)
    except (OSError, ValueError) as erro:
        parser.exit(1, f"Limpeza interrompida: {erro}\n")
    print(f"{indicadores['registros_lidos']} registros analisados.")
    print(f"{indicadores['processos_na_base']} processos e {indicadores['pagamentos_na_base']} pagamentos na base.")
    print(f"Resultados em {argumentos.saida}")


if __name__ == "__main__":
    main()
