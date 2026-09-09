from __future__ import annotations

import re
import unicodedata

# Palabras muy comunes que no ayudan al ranking
_STOP = {
    "el",
    "la",
    "los",
    "las",
    "un",
    "una",
    "de",
    "del",
    "en",
    "y",
    "o",
    "a",
    "que",
    "por",
    "para",
    "con",
    "se",
    "su",
    "al",
    "es",
    "me",
    "mi",
    "te",
    "tu",
    "si",
    "no",
    "como",
    "qué",
    "que",
    "hay",
    "tiene",
    "tengo",
    "sobre",
    "este",
    "esta",
    "eso",
}


def _fold(text: str) -> str:
    """Quita acentos para matchear diabetes/cáncer sin importar tildes."""
    norm = unicodedata.normalize("NFD", text.lower())
    return "".join(ch for ch in norm if unicodedata.category(ch) != "Mn")


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]{3,}", _fold(text))
    return {w for w in words if w not in _STOP}


def _split_chunks(text: str, target_size: int = 1200) -> list[str]:
    # Preferir cortes por secciones numeradas del documento
    parts = re.split(r"(?=\n\d{1,2}\.\d{0,2}\s)", text)
    chunks: list[str] = []
    buf = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if len(buf) + len(part) < target_size:
            buf = f"{buf}\n{part}".strip()
        else:
            if buf:
                chunks.append(buf)
            if len(part) <= target_size * 2:
                buf = part
            else:
                # párrafos largos: partir por líneas
                lines = part.splitlines()
                buf = ""
                for line in lines:
                    if len(buf) + len(line) < target_size:
                        buf = f"{buf}\n{line}".strip()
                    else:
                        if buf:
                            chunks.append(buf)
                        buf = line
        if len(buf) >= target_size:
            chunks.append(buf)
            buf = ""
    if buf:
        chunks.append(buf)
    return chunks or [text[:target_size]]


def select_business_context(full_context: str, user_message: str, max_chars: int = 32000) -> str:
    """
    Si el contexto es enorme (PDF completo), selecciona los fragmentos más
    relevantes al mensaje + un encabezado fijo, para cubrir TODOS los temas
    bajo demanda sin saturar el modelo.
    """
    full = (full_context or "").strip()
    if not full:
        return ""
    if len(full) <= max_chars:
        return full

    # Encabezado: instrucciones + primeras secciones (producto/paquetes)
    header = full[:4500]
    rest = full[4500:]
    chunks = _split_chunks(rest)
    query = _tokens(user_message)

    scored: list[tuple[float, str]] = []
    query_fold = _fold(user_message)
    for chunk in chunks:
        ctoks = _tokens(chunk)
        if not ctoks:
            continue
        overlap = len(query & ctoks)
        bonus = 0.0
        low = _fold(chunk)
        for key in (
            "exclus",
            "deducible",
            "coaseguro",
            "maternidad",
            "espera",
            "paquete",
            "reembolso",
            "pago directo",
            "extranjero",
            "preexist",
            "recuperacion",
            "escudo",
            "hospital",
            "cancer",
            "diabetes",
            "vih",
            "ambulancia",
            "maternidad",
            "red ",
        ):
            if key in low and key in query_fold:
                bonus += 2.0
        # Preferir chunks que contienen términos literales de la pregunta
        for term in query:
            if len(term) >= 5 and term in low:
                bonus += 1.0
        score = overlap + bonus
        if score > 0:
            scored.append((score, chunk))

    scored.sort(key=lambda x: x[0], reverse=True)

    selected = [header]
    used = len(header)
    for _, chunk in scored:
        if used + len(chunk) + 20 > max_chars:
            continue
        selected.append(chunk)
        used += len(chunk) + 20
        if used >= max_chars * 0.92:
            break

    # Si no hubo overlap, tomar cuerpo medio del documento además del header
    if len(selected) == 1:
        mid = rest[: max_chars - len(header) - 100]
        selected.append(mid)

    note = (
        "\n\n[Nota interna: el documento completo de condiciones está cargado; "
        "arriba van las secciones más relevantes a la pregunta. Si falta detalle, "
        "pide más datos o escala a asesor.]\n"
    )
    return "\n\n---\n\n".join(selected) + note
