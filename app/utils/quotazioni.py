from sqlalchemy.orm import Session
from app.models import SiteAdminSettings
from app.auth_helpers import is_dealer_user


def calcola_quotazione(offerta, quotazione, current_user, db: Session):
    """
    Calcola il canone mensile con applicazione provvigione admin + dealer:
    - Provvigione = % su prezzo_listino
    - Valore spalmato sui canoni
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

    prezzo_listino = float(offerta.prezzo_listino)

    # Provvigione Admin
    settings_admin = db.query(SiteAdminSettings).filter(
        SiteAdminSettings.admin_id == offerta.id_admin,
        SiteAdminSettings.dealer_id.is_(None)
    ).first()
    prov_admin = (settings_admin.prov_vetrina or 0)
    canone_admin = canone_base + (prezzo_listino * prov_admin / 100) / durata

    # Se dealer → applica anche provvigione dealer
    if is_dealer_user(current_user):
        settings_dealer = db.query(SiteAdminSettings).filter(
            SiteAdminSettings.admin_id == offerta.id_admin,
            SiteAdminSettings.dealer_id == current_user.id
        ).first()
        prov_dealer = (settings_dealer.prov_vetrina or 0) if settings_dealer else 0
        canone_finale = canone_admin + (prezzo_listino * prov_dealer / 100) / durata
    else:
        canone_finale = canone_admin

    return durata, km, round(canone_finale, 2)
