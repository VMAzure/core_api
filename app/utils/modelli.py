import re

def pulisci_modello(modello: str) -> str:
    """
    Normalizza e pulisce il nome del modello del veicolo.

    - Rimuove anni compresi tra 2010 e 2030.
    - Gestisce eccezioni specifiche DOPO la rimozione degli anni.
    - Rimuove numeri romani da I a X solo se isolati a fine stringa.

    Args:
        modello (str): Il nome originale del modello.

    Returns:
        str: Il nome del modello normalizzato.
    """

    # Rimuovi gli anni (2010-2030)
    modello_pulito = re.sub(r'\b(20[1-2][0-9]|2030)\b', '', modello).strip()

    # Eccezioni specifiche per modelli particolari (DOPO rimozione anni)
    eccezioni = {
        "GLE - V167": "GLE",
        "Model X": "Model X",
    }

    # Verifica eccezioni dopo pulizia degli anni
    if modello_pulito in eccezioni:
        return eccezioni[modello_pulito]

    # Rimuovi numeri romani SOLO isolati alla fine
    modello_pulito = re.sub(r'\s+(I|II|III|IV|V|VI|VII|VIII|IX|X)$', '', modello_pulito).strip()

    return modello_pulito
