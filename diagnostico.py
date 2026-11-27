import json
from pathlib import Path
from collections import Counter
from datetime import datetime
import re


BASE_DIR = Path(__file__).resolve().parent

with open(BASE_DIR / "dados" / "pagamentos.json", encoding="utf-8") as arquivo:
    pagamentos = json.load(arquivo)

print("Total de registros:", len(pagamentos))

contagem = Counter(pagamento["evento_id"] for pagamento in pagamentos)

print("IDs únicos:", len(contagem))

print("\nRegistros com IDs repetidos:")

for pagamento in pagamentos:
    evento_id = pagamento["evento_id"]

    if contagem[evento_id] > 1:
        print(pagamento)

print("\nValores fora do padrão:")

for pagamento in pagamentos:

    if not isinstance(pagamento["valor"], (float, int,)):
        print(pagamento)


for pagamento in pagamentos:
    try:
        datetime.strptime(pagamento["data_pagamento"], "%Y-%m-%d")
    except ValueError:
        print("\nData fora do padrão:", pagamento)


for pagamento in pagamentos:

    if not re.fullmatch(r"\d{7}-\d{2}\.\d{4}\.\d{1}\.\d{2}\.\d{4}", pagamento["processo"]):
        print("\nProcessos fora do padrão CNJ:" , pagamento)



   