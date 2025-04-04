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
