from pathlib import Path

extracted = Path(r"C:\Users\GERGR\Projects\ValerIA\app\contexts\_extracted_pmmi.txt").read_text(encoding="utf-8")

# Quitar marcadores de página para dejar texto continuo más limpio
lines = []
for line in extracted.splitlines():
    if line.startswith("===== PAGE "):
        continue
    lines.append(line)
body = "\n".join(lines).strip()

preamble = """CONTEXTO COMPLETO DEL PRODUCTO — Úsalo como fuente de verdad.
Producto: Protección Médica a tu Medida Individual/Familiar (PMMI) 2026
Aseguradora: MAPFRE México S.A.
Documento: Condiciones Generales completas (todas las secciones del PDF).

Instrucciones para ValerIA:
- Responde con base en ESTE documento. Cubre TODOS los temas: definiciones, objeto, contrato, paquetes, gastos cubiertos, periodos de espera, límites (deducible/coaseguro/redes/pago directo/reembolso), exclusiones, riesgos no amparados, coberturas opcionales (Tu recuperación, plus, atención alternativa, Donde tú vayas, Tu protección, soporte asistencial, Tu escudo, Tus días seguros) y cláusulas generales.
- Si el cliente pregunta por un tema puntual, busca la sección correspondiente y resume en lenguaje claro de WhatsApp (corto), sin inventar.
- NO inventes primas ni digas que algo está cubierto al 100% si depende de carátula/paquete/endoso.
- Para cotizar, contratar, siniestro o interpretación legal fina: escala a un asesor humano.
- Contact Center MAPFRE 24/7 y www.mapfre.com.mx para directorio/tabulador.
- No menciones Seguros Mexicali Plus ni productos ajenos.

=== INICIO CONDICIONES GENERALES PMMI 2026 ===

"""

footer = """

=== FIN CONDICIONES GENERALES ===

Recordatorio final: si algo no aparece arriba o hay duda entre paquetes/carátula, no inventes; ofrece pasar con un asesor.
"""

out = Path(r"C:\Users\GERGR\Projects\ValerIA\app\contexts\proteccion_medica_mapfre.txt")
out.write_text(preamble + body + footer, encoding="utf-8")
print("wrote", out.stat().st_size, "bytes", "chars", len(preamble) + len(body) + len(footer))
