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

def aggiorna_rating_convenienza(db: Session):
    from app.models import NltOfferte, NltQuotazioni, NltOfferteRating
    from app.utils.quotazioni import calcola_quotazione  # evita import circolari
    from app.auth_helpers import is_dealer_user  # se necessario, ma lo bypassiamo con dealer_context=False

    from datetime import datetime

    offerte_raw = (
        db.query(NltOfferte, NltQuotazioni)
        .join(NltQuotazioni, NltOfferte.id_offerta == NltQuotazioni.id_offerta)
        .filter(
            NltOfferte.attivo.is_(True),
            NltOfferte.prezzo_totale.isnot(None),
            NltQuotazioni.mesi_48_10.isnot(None)
        )
        .all()
    )

    risultati = []

    for offerta, quotazione in offerte_raw:
        from types import SimpleNamespace
        dummy_user = SimpleNamespace(role="admin", id=offerta.id_admin)

        durata, km, canone_finale, _ = calcola_quotazione(
            offerta, quotazione,
            current_user=dummy_user,
            db=db,
            dealer_context=False,
            dealer_id=None
        )


        if not durata or not km or not canone_finale:
            continue

        costo_km = (canone_finale * durata) / km
        valore_km = float(offerta.prezzo_totale) / km
        indice = valore_km / costo_km if costo_km > 0 else 0

        risultati.append({
            "id_offerta": offerta.id_offerta,
            "costo_km": round(costo_km, 4),
            "valore_km": round(valore_km, 4),
            "indice_convenienza": round(indice, 4)
        })

    risultati.sort(key=lambda x: x["indice_convenienza"], reverse=True)
    totale = len(risultati)

    from sqlalchemy.orm.exc import NoResultFound

    for i, r in enumerate(risultati):
        percentile = i / totale
        if percentile <= 0.2:
            rating = 5
        elif percentile <= 0.4:
            rating = 4
        elif percentile <= 0.6:
            rating = 3
        elif percentile <= 0.8:
            rating = 2
        else:
            rating = 1

        try:
            record = db.query(NltOfferteRating).filter_by(id_offerta=r["id_offerta"]).one_or_none()
            if record:
                record.costo_km = r["costo_km"]
                record.valore_km = r["valore_km"]
                record.indice_convenienza = r["indice_convenienza"]
                record.rating_convenienza = rating
                record.updated_at = datetime.utcnow()
            else:
                db.add(NltOfferteRating(
                    id_offerta=r["id_offerta"],
                    costo_km=r["costo_km"],
                    valore_km=r["valore_km"],
                    indice_convenienza=r["indice_convenienza"],
                    rating_convenienza=rating
                ))
        except NoResultFound:
            continue

    db.commit()
