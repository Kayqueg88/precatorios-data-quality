import csv
import json
import shutil
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from limpeza import executar
from regras import chave_cnj, data_pagamento, prazo_da_apresentacao, valor_decimal


DADOS = Path(__file__).resolve().parents[1] / "dados"


class RegrasTest(unittest.TestCase):
    def test_moeda_localizada_com_exatidao(self):
        self.assertEqual(valor_decimal("2.500,50"), Decimal("2500.50"))
        self.assertEqual(valor_decimal("0.17") + valor_decimal("0.04"), Decimal("0.21"))
        for valor in (None, True, False, "1,234.56", "NaN"):
            with self.subTest(valor=valor):
                self.assertIsNone(valor_decimal(valor))

    def test_cnj_mantem_zeros_e_rejeita_forma_inventada(self):
        self.assertEqual(chave_cnj("0012345-10.2019.8.26.0053"), "00123451020198260053")
        self.assertEqual(chave_cnj("00234562120208260053"), "00234562120208260053")
        for valor in (12345, "", "0012345/10/2019/8/26/0053"):
            self.assertIsNone(chave_cnj(valor))

    def test_datas_validam_o_calendario(self):
        self.assertEqual(data_pagamento("10/04/2025"), date(2025, 4, 10))
        self.assertEqual(data_pagamento("2024-02-29"), date(2024, 2, 29))
        for valor in (None, "2025-02-29", "2025-4-02", "31/04/2025"):
            with self.subTest(valor=valor), self.assertRaises(ValueError):
                data_pagamento(valor)

    def test_prazo_no_corte_e_com_conversao_de_fuso(self):
        self.assertEqual(prazo_da_apresentacao("2025-04-02")[1], date(2026, 12, 31))
        self.assertEqual(prazo_da_apresentacao("2025-04-03")[1], date(2027, 12, 31))
        self.assertEqual(prazo_da_apresentacao("2025-04-03T01:00:00Z"),
                         (date(2025, 4, 2), date(2026, 12, 31)))
        with self.assertRaises(ValueError):
            prazo_da_apresentacao("2025-04-02T23:30:00")


class LimpezaTest(unittest.TestCase):
    def setUp(self):
        temporario = tempfile.TemporaryDirectory()
        self.addCleanup(temporario.cleanup)
        pasta = Path(temporario.name)
        self.dados = shutil.copytree(DADOS, pasta / "dados")
        self.saida = pasta / "saida"

    def executar_e_ler(self):
        executar(self.dados, self.saida)
        base = json.loads((self.saida / "base_limpa.json").read_text(encoding="utf-8"))
        relatorio = json.loads((self.saida / "relatorio_limpeza.json").read_text(encoding="utf-8"))
        return base, relatorio

    def gravar_eventos(self, eventos):
        (self.dados / "pagamentos.json").write_text(json.dumps(eventos), encoding="utf-8")

    def evento(self, **campos):
        dados = {
            "evento_id": "exemplo", "processo": "0012345-10.2019.8.26.0053",
            "valor": 100, "data_pagamento": "2025-03-10", "tipo": "pagamento",
            "atualizado_em": "2025-03-10T10:00:00-03:00",
        }
        dados.update(campos)
        return dados

    def test_amostra_e_reprocessamento_geram_arquivos_identicos(self):
        originais = {p.name: p.read_bytes() for p in self.dados.iterdir()}
        base, relatorio = self.executar_e_ler()
        primeira_saida = {p.name: p.read_bytes() for p in self.saida.iterdir()}
        self.executar_e_ler()
        self.assertEqual(primeira_saida, {p.name: p.read_bytes() for p in self.saida.iterdir()})
        self.assertEqual(originais, {p.name: p.read_bytes() for p in self.dados.iterdir()})
        eventos = {p["evento_id"]: p["valor"] for p in base["pagamentos"]}
        self.assertEqual(eventos, {
            "ev-001": "15500.00", "ev-002": "2500.50", "ev-003": "8000.00",
            "ev-005": "1200.00", "ev-006": "5000.00", "ev-008": "3000.00",
        })
        situacoes = relatorio["indicadores"]["por_situacao"]
        self.assertEqual(len(relatorio["registros"]), 29)
        self.assertEqual(sum(situacoes.values()), 29)
        self.assertEqual(situacoes["descartado"], 2)

    def test_versao_recente_e_duplicata_elegem_um_evento(self):
        anterior = self.evento()
        recente = self.evento(valor=150, atualizado_em="2025-03-11T01:00:00Z")
        self.gravar_eventos([recente, anterior, anterior])
        base, relatorio = self.executar_e_ler()
        self.assertEqual([e["valor"] for e in base["pagamentos"]], ["150.00"])
        registros = [r for r in relatorio["registros"] if r["arquivo"] == "pagamentos.json"]
        self.assertEqual([r["situacao"] for r in registros], ["corrigido", "descartado", "descartado"])
        self.assertNotEqual(registros[1]["motivos"], registros[2]["motivos"])

    def test_empate_no_mesmo_instante_e_nova_versao_invalida_ficam_pendentes(self):
        for nova_versao in (
            self.evento(valor=120, atualizado_em="2025-03-10T13:00:00Z"),
            self.evento(valor=None, atualizado_em="2025-03-11T13:00:00Z"),
            self.evento(data_pagamento="2025-03-11", atualizado_em="2025-03-11T13:00:00Z"),
        ):
            with self.subTest(nova_versao=nova_versao):
                self.gravar_eventos([self.evento(), nova_versao])
                base, relatorio = self.executar_e_ler()
                self.assertEqual(base["pagamentos"], [])
                estados = [r["situacao"] for r in relatorio["registros"] if r["arquivo"] == "pagamentos.json"]
                self.assertEqual(estados, ["pendente", "pendente"])

    def test_negativo_zero_nulo_booleano_estorno_e_orfaos_preservados(self):
        casos = [
            dict(valor=-1), dict(valor=0), dict(valor=None), dict(valor=True),
            dict(tipo="estorno"), dict(processo=""),
            dict(processo="9999999-99.2025.8.26.9999"),
            dict(processo="0067890-65.2016.8.26.0053"),
            dict(data_pagamento="2025-02-30"),
        ]
        self.gravar_eventos([self.evento(evento_id=str(i), **campos) for i, campos in enumerate(casos)])
        base, relatorio = self.executar_e_ler()
        self.assertFalse(base["pagamentos"])
        pendencias = [r for r in relatorio["registros"] if r["arquivo"] == "pagamentos.json"]
        self.assertEqual([r["situacao"] for r in pendencias], ["pendente"] * len(casos))
        self.assertIsNone(pendencias[2]["original"]["valor"])
        self.assertIs(pendencias[3]["original"]["valor"], True)

    def test_conflitos_de_cadastro_e_de_prazo_preservam_as_fontes(self):
        base, relatorio = self.executar_e_ler()
        por_processo = {p["processo"]: p for p in base["processos"]}
        self.assertEqual(set(por_processo), {
            "00123451020198260053", "00234562120208260053",
            "00345673220188260405", "00456784320215020011",
        })
        self.assertNotIn("valor_face", por_processo["00234562120208260053"])
        self.assertNotIn("ente_devedor", por_processo["00456784320215020011"])
        self.assertEqual(por_processo["00123451020198260053"]["prazo_pagamento"], "2026-12-31")
        self.assertNotIn("prazo_pagamento", por_processo["00456784320215020011"])
        apresentacoes = [r for r in relatorio["registros"] if r["arquivo"] == "apresentacoes.json"]
        self.assertEqual(apresentacoes[4]["normalizado"]["prazo_pagamento"], "2026-12-31")
        self.assertEqual(apresentacoes[4]["situacao"], "pendente")
        self.assertTrue(all(e["processo"] in por_processo for e in base["pagamentos"]))

    def test_saida_na_pasta_dos_originais_e_bloqueada(self):
        with self.assertRaises(ValueError):
            executar(self.dados, self.dados / "saida")
        self.assertFalse((self.dados / "saida").exists())

    def test_valor_fracionario_excessivo_e_preservado_sem_arredondar(self):
        texto = json.dumps([self.evento(valor="FRACAO")]).replace('"FRACAO"', "2.123456789012345678")
        (self.dados / "pagamentos.json").write_text(texto, encoding="utf-8")
        base, relatorio = self.executar_e_ler()
        self.assertEqual(base["pagamentos"], [])
        registro = relatorio["registros"][0]
        self.assertEqual(registro["situacao"], "pendente")
        self.assertEqual(registro["original"]["valor"], {"numero_json_decimal": "2.123456789012345678"})

    def test_cadastro_repetido_torna_o_vinculo_ambiguo(self):
        caminho = self.dados / "hub.csv"
        with caminho.open(encoding="utf-8", newline="") as arquivo:
            linhas = list(csv.reader(arquivo))
        with caminho.open("a", encoding="utf-8", newline="") as arquivo:
            csv.writer(arquivo).writerow(linhas[1])
        base, relatorio = self.executar_e_ler()
        self.assertNotIn("00123451020198260053", {p["processo"] for p in base["processos"]})
        self.assertNotIn("ev-001", {p["evento_id"] for p in base["pagamentos"]})
        cadastros = [r for r in relatorio["registros"]
                     if r["arquivo"] == "hub.csv" and r["normalizado"].get("processo") == "00123451020198260053"]
        self.assertEqual([r["situacao"] for r in cadastros], ["pendente", "pendente"])

    def test_csv_incompleto_e_json_quebrado_tem_tratamentos_distintos(self):
        caminho = self.dados / "hub.csv"
        with caminho.open("a", encoding="utf-8", newline="") as arquivo:
            csv.writer(arquivo).writerow(["0077777-77.2020.8.26.0053"])
        _, relatorio = self.executar_e_ler()
        linha = [r for r in relatorio["registros"] if r["arquivo"] == "hub.csv"][-1]
        self.assertEqual(linha["situacao"], "pendente")
        original_saida = (self.saida / "base_limpa.json").read_bytes()
        (self.dados / "pagamentos.json").write_text("não é JSON", encoding="utf-8")
        with self.assertRaises(ValueError):
            executar(self.dados, self.saida)
        self.assertEqual((self.saida / "base_limpa.json").read_bytes(), original_saida)
