from sqlalchemy.orm import Session
from app.models import SiteAdminSettings
from app.auth_helpers import is_dealer_user


def calcola_quotazione(offerta, quotazione, current_user, db: Session, dealer_context=False, dealer_id=None):
    """
    Calcola il canone mensile con provvigione admin e dealer applicate sul prezzo_listino.
    """
    if not offerta or not quotazione or not offerta.prezzo_listino:
        return None, None, None

    # Selezione canone base e durata
    if offerta.solo_privati and quotazione.mesi_48_30:
        durata, km, canone_base = 48, 30000, quotazione.mesi_48_30
    elif quotazione.mesi_36_10:
        durata, km, canone_base = 36, 10000, quotazione.mesi_36_10
    elif quotazione.mesi_48_10:
        durata, km, canone_base = 48, 10000, quotazione.mesi_48_10
    else:
        return None, None, None

    if not durata or durata <= 0:
        return None, None, None

    prezzo_listino = float(offerta.prezzo_listino)
    canone_base = float(canone_base)

    # Provvigione Admin
    # Recupero provvigioni
    settings_admin = db.query(SiteAdminSettings).filter(
        SiteAdminSettings.admin_id == offerta.id_admin,
        SiteAdminSettings.dealer_id.is_(None)
    ).first()
    prov_admin = (settings_admin.prov_vetrina or 0)

    prov_dealer = 0
    if dealer_context or is_dealer_user(current_user):
        dealer_id_effettivo = dealer_id or current_user.id
        settings_dealer = db.query(SiteAdminSettings).filter(
            SiteAdminSettings.admin_id == offerta.id_admin,
            SiteAdminSettings.dealer_id == dealer_id_effettivo
        ).first()
        prov_dealer = (settings_dealer.prov_vetrina or 0) if settings_dealer else 0

    # Calcolo unico dell'incremento totale
    incremento_totale = prezzo_listino * (prov_admin + prov_dealer) / 100
    canone_finale = canone_base + (incremento_totale / durata)


    return durata, km, round(canone_finale, 2)
