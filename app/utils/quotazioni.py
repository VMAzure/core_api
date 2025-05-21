def calcola_quotazione(offerta, quotazione):
    """
    Restituisce (durata_mesi, km_inclusi, canone_mensile) basandosi su priorità aziendali:
    - 48 mesi / 30k km per privati se disponibile
    - altrimenti 36 mesi / 10k km
    - altrimenti 48 mesi / 10k km
    """
    if not offerta or not quotazione:
        return None, None, None

    if offerta.solo_privati and quotazione.mesi_48_30:
        return 48, 30000, quotazione.mesi_48_30
    elif quotazione.mesi_36_10:
        return 36, 10000, quotazione.mesi_36_10
    elif quotazione.mesi_48_10:
        return 48, 10000, quotazione.mesi_48_10

    return None, None, None
