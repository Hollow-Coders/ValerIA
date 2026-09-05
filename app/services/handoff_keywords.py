HANDOFF_KEYWORDS = (
    "humano",
    "persona real",
    "persona",
    "asesor",
    "asesora",
    "agente",
    "hablar con alguien",
    "hablar con una persona",
    "quiero hablar",
    "pasame con",
    "pásame con",
    "comunicame con",
    "comunícame con",
    "no quiero bot",
    "no robot",
)


def wants_human_handoff(message: str) -> bool:
    text = message.lower().strip()
    return any(keyword in text for keyword in HANDOFF_KEYWORDS)
