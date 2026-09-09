from pathlib import Path
from pypdf import PdfReader

reader = PdfReader(r"C:\Users\GERGR\Projects\ValerIA\app\contexts\_source_proteccion_medica.pdf")
parts = []
for i, page in enumerate(reader.pages):
    t = page.extract_text() or ""
    parts.append(f"\n\n===== PAGE {i+1} =====\n{t}")
text = "".join(parts)
out = Path(r"C:\Users\GERGR\Projects\ValerIA\app\contexts\_extracted_pmmi.txt")
out.write_text(text, encoding="utf-8", errors="replace")
print("pages", len(reader.pages), "chars", len(text))
print("has ó", "ó" in text, "has Periodo", "Periodo" in text or "Período" in text)
print(text[33100:33220])
