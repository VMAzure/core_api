from sqlalchemy.orm import Session
from app.models import SiteAdminSettings
from app.auth_helpers import is_dealer_user

def calcola_quotazione(offerta, quotazione, current_user, db: Session, dealer_context=False, dealer_id=None):
    if not offerta or not quotazione or not offerta.prezzo_listino:
        return None, None, None, None

    # Selezione canone base
    if offerta.solo_privati and quotazione.mesi_48_30:
        durata, km, canone_base = 48, 30000, quotazione.mesi_48_30
    elif quotazione.mesi_36_10:
        durata, km, canone_base = 36, 10000, quotazione.mesi_36_10
    elif quotazione.mesi_48_10:
        durata, km, canone_base = 48, 10000, quotazione.mesi_48_10
    else:
        return None, None, None, None

    if not durata or durata <= 0:
        return None, None, None, None

    canone_base = float(canone_base)

    # Base imponibile = prezzo netto (senza IVA)
    prezzo_netto = float(offerta.prezzo_totale) / 1.22

    # Recupero provvigioni
    settings_admin = db.query(SiteAdminSettings).filter(
        SiteAdminSettings.admin_id == offerta.id_admin,
        SiteAdminSettings.dealer_id.is_(None)
    ).first()

    prov_admin = float(settings_admin.prov_vetrina or 0)
    slug_finale = settings_admin.slug if settings_admin else None

    prov_dealer = 0.0
    if dealer_context or is_dealer_user(current_user):
        dealer_id_effettivo = dealer_id or current_user.id
        settings_dealer = db.query(SiteAdminSettings).filter(
            SiteAdminSettings.admin_id == offerta.id_admin,
            SiteAdminSettings.dealer_id == dealer_id_effettivo
        ).first()

        if settings_dealer:
            prov_dealer = float(settings_dealer.prov_vetrina or 0)
            if settings_dealer.slug:
                slug_finale = settings_dealer.slug

    if offerta.id_player == 5:
        prov_admin = 0.0
        prov_dealer = 0.0

    incremento_totale = prezzo_netto * (prov_admin + prov_dealer) / 100.0
    canone_finale = canone_base + (incremento_totale / durata)

    return durata, km, round(canone_finale, 2), slug_finale


def calcola_quotazione_custom(offerta, durata, km, canone_base, current_user, db: Session, dealer_context=False, dealer_id=None):
    canone_base = float(canone_base)

    prezzo_netto = float(offerta.prezzo_listino) / 1.22

    settings_admin = db.query(SiteAdminSettings).filter(
        SiteAdminSettings.admin_id == offerta.id_admin,
        SiteAdminSettings.dealer_id.is_(None)
    ).first()

    prov_admin = float(settings_admin.prov_vetrina or 0)
    slug_finale = settings_admin.slug if settings_admin else None

    prov_dealer = 0.0
    if dealer_context or is_dealer_user(current_user):
        dealer_id_effettivo = dealer_id or current_user.id
        settings_dealer = db.query(SiteAdminSettings).filter(
            SiteAdminSettings.admin_id == offerta.id_admin,
            SiteAdminSettings.dealer_id == dealer_id_effettivo
        ).first()
        if settings_dealer:
            prov_dealer = float(settings_dealer.prov_vetrina or 0)
            if settings_dealer.slug:
                slug_finale = settings_dealer.slug

    if offerta.id_player == 5:
        prov_admin = 0.0
        prov_dealer = 0.0

    incremento_totale = prezzo_netto * (prov_admin + prov_dealer) / 100.0
    canone_finale = canone_base + (incremento_totale / durata)

    return durata, km, round(canone_finale, 2), slug_finale

