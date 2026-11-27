"""Regras de interpretação usadas no diagnóstico e na limpeza."""

import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal


CNJ_FORMATADO = re.compile(r"[0-9]{7}-[0-9]{2}\.[0-9]{4}\.[0-9]\.[0-9]{2}\.[0-9]{4}")
DATA_ISO = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
DATA_BR = re.compile(r"[0-9]{2}/[0-9]{2}/[0-9]{4}")
MOEDA_BR = re.compile(r"-?(?:[0-9]+|[0-9]{1,3}(?:\.[0-9]{3})+),[0-9]{1,2}")
MOEDA_ISO = re.compile(r"-?[0-9]+(?:\.[0-9]{1,2})?")
FUSO_ANALISE = timezone(timedelta(hours=-3))


def chave_cnj(processo):
    if isinstance(processo, str):
        processo = processo.strip()
        if CNJ_FORMATADO.fullmatch(processo):
            return processo.replace("-", "").replace(".", "")
        if re.fullmatch(r"[0-9]{20}", processo):
            return processo
    return None


def valor_decimal(valor):
    if type(valor) in (int, float, Decimal):
        numero = Decimal(str(valor))
        return numero if numero.is_finite() else None
    if isinstance(valor, str):
        valor = valor.strip()
        if MOEDA_BR.fullmatch(valor):
            return Decimal(valor.replace(".", "").replace(",", "."))
        if MOEDA_ISO.fullmatch(valor):
            return Decimal(valor)
    return None


def chave_ente(nome):
    decomposicao = unicodedata.normalize("NFD", nome.casefold())
    sem_acentos = "".join(letra for letra in decomposicao if not unicodedata.combining(letra))
    return " ".join(sem_acentos.split())


def data_pagamento(texto):
    if isinstance(texto, str):
        if DATA_ISO.fullmatch(texto):
            return date.fromisoformat(texto)
        if DATA_BR.fullmatch(texto):
            return datetime.strptime(texto, "%d/%m/%Y").date()
    raise ValueError("data de pagamento ausente ou em formato desconhecido")


def instante_iso(texto):
    if not isinstance(texto, str):
        raise ValueError("instante ausente ou não textual")
    # Compatibilidade com datetime.fromisoformat() do Python 3.10.
    if texto.endswith("Z"):
        texto = texto[:-1] + "+00:00"
    instante = datetime.fromisoformat(texto)
    if instante.tzinfo is None:
        raise ValueError("data com horário sem fuso")
    return instante


def prazo_da_apresentacao(apresentado_em):
    if isinstance(apresentado_em, str) and DATA_ISO.fullmatch(apresentado_em):
        dia = date.fromisoformat(apresentado_em)
    else:
        dia = instante_iso(apresentado_em).astimezone(FUSO_ANALISE).date()
    anos = 1 if dia <= date(dia.year, 4, 2) else 2
    return dia, date(dia.year + anos, 12, 31)
