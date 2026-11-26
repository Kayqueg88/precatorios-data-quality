import json
from pathlib import Path
from collections import Counter

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