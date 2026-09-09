from pathlib import Path
import re

text = Path(r"C:\Users\GERGR\Projects\ValerIA\app\contexts\_extracted_pmmi.txt").read_text(encoding="utf-8")
print("len", len(text))
print("sample", repr(text[33000:33150]))

needles = [
    "Objeto del seguro",
    "4. Paquetes",
    "Cobertura elemental",
    "periodo de espera",
    "Período de espera",
    "Exclusiones",
    "Tu recuperación",
    "Donde tú vayas",
    "Tu protección",
    "Tu escudo",
    "Tus días seguros",
    "Cláusulas generales",
    "Pago directo",
    "Reembolso",
]
for n in needles:
    idxs = [m.start() for m in re.finditer(re.escape(n), text)]
    print(n, idxs[:6], "n=", len(idxs))
