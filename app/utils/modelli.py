import re

def pulisci_modello(modello: str) -> str:
    """
    Normalizza e pulisce il nome del modello del veicolo.

    - Gestisce eccezioni specifiche prima della pulizia generale.
    - Rimuove anni compresi tra 2010 e 2030.
    - Rimuove numeri romani da I a X isolati con spazio.

    Args:
        modello (str): Il nome originale del modello.

    Returns:
        str: Il nome del modello normalizzato.
    """

    # Eccezioni specifiche per modelli particolari (prioritarie)
    eccezioni = {
       "Tesla Moldel X": "Tesla Model X",
       "Mercedes GLE - V167": "Mercedes GLE", 
       # aggiungi qui altre eccezioni specifiche
    }

    # Verifica eccezioni prima di qualsiasi altra pulizia
    if modello in eccezioni:
        return eccezioni[modello]

    # Regole generiche di pulizia
    modello_pulito = re.sub(r'\b(20[1-2][0-9]|2030)\b', '', modello).strip()
    modello_pulito = re.sub(r'\s+(I|II|III|IV|V|VI|VII|VIII|IX|X)\b', '', modello_pulito).strip()

    return modello_pulito
