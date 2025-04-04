from sqlalchemy import text

def pulizia_massiva_modelli(db):
    print("🔄 Avvio pulizia massiva modelli...")

    # 1. Rimozione numeri romani isolati
    db.execute(text("""
        UPDATE mnet_modelli
        SET descrizione = REGEXP_REPLACE(
            ' ' || TRIM(descrizione) || ' ',
            '\\s(I{1,3}|IV|V|VI{0,3}|IX|X)\\s',
            ' ',
            'g'
        )
        WHERE ' ' || TRIM(descrizione) || ' ' ~ '\\s(I{1,3}|IV|V|VI{0,3}|IX|X)\\s';
    """))

    # 2. Rimozione anni dal 2010 al 2030
    db.execute(text("""
        UPDATE mnet_modelli
        SET descrizione = REGEXP_REPLACE(
            TRIM(descrizione),
            '\\s?(20[1-2][0-9]|2030)\\s?',
            ' ',
            'g'
        )
        WHERE descrizione ~ '\\s?(20[1-2][0-9]|2030)\\s?';
    """))

    # 3. Normalizzazione spazi doppi
    db.execute(text("""
        UPDATE mnet_modelli
        SET descrizione = REGEXP_REPLACE(TRIM(descrizione), '\\s{2,}', ' ', 'g');
    """))

    # 4. Applicazione correzioni manuali da tabella
    db.execute(text("""
        UPDATE mnet_modelli
        SET descrizione = c.corretto
        FROM mnet_modelli_correzioni c
        WHERE TRIM(mnet_modelli.descrizione) = c.originale;
    """))

    db.commit()
    print("✅ Pulizia completata.")

import re

def pulisci_modello(modello: str) -> str:
    """Pulisce un nome modello rimuovendo anni e numeri romani finali"""
    if not modello:
        return ""

    modello_pulito = re.sub(r'\b(20[1-2][0-9]|2030)\b', '', modello).strip()

    eccezioni = {
        "Model X": "Model X",
        "Classe": "Classe V",
    }

    if modello_pulito in eccezioni:
        return eccezioni[modello_pulito]

    modello_pulito = re.sub(r'\s+(I|II|III|IV|V|VI|VII|VIII|IX|X)$', '', modello_pulito).strip()
    return modello_pulito

