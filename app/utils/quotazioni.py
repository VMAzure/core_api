from sqlalchemy.orm import Session
from app.models import SiteAdminSettings
from app.auth_helpers import is_dealer_user


def calcola_quotazione(offerta, quotazione, current_user, db: Session, dealer_context=False):
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
    settings_admin = db.query(SiteAdminSettings).filter(
        SiteAdminSettings.admin_id == offerta.id_admin,
        SiteAdminSettings.dealer_id.is_(None)
    ).first()
    prov_admin = (settings_admin.prov_vetrina or 0)
    prov_admin_amount = prezzo_listino * prov_admin / 100
    canone_admin = canone_base + (prov_admin_amount / durata)

    # Se dealer → applica anche provvigione dealer
    if dealer_context or is_dealer_user(current_user):
        settings_dealer = db.query(SiteAdminSettings).filter(
            SiteAdminSettings.admin_id == offerta.id_admin,
            SiteAdminSettings.dealer_id == current_user.id
        ).first()
        prov_dealer = (settings_dealer.prov_vetrina or 0) if settings_dealer else 0
        prov_dealer_amount = prezzo_listino * prov_dealer / 100
        canone_finale = canone_admin + (prov_dealer_amount / durata)
    else:
        canone_finale = canone_admin

    return durata, km, round(canone_finale, 2)
