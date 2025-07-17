from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, cast, Date
from datetime import datetime, timedelta

from app.database import get_db
from app.models import NltOfferteClick, NltOfferte, User
from app.auth_helpers import (
    get_admin_id,
    get_dealer_id,
    is_admin_user,
    get_settings_owner_id
)
from app.routes.nlt import get_current_user

router = APIRouter(
    prefix="/analytics",
    tags=["Analytics"]
)

@router.get("/offerte-piu-cliccate")
def offerte_piu_cliccate(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    from app.auth_helpers import get_dealer_id, get_admin_id, is_admin_user

    if is_admin_user(current_user):
        admin_id = get_admin_id(current_user)

        # Click aggregati per offerta e dealer
        query = db.query(
            NltOfferteClick.id_offerta,
            func.count().label("totale_click"),
            NltOfferte.marca,
            NltOfferte.modello,
            NltOfferte.versione,
            NltOfferte.solo_privati,
            User.id.label("dealer_id"),
            User.ragione_sociale
        ).join(NltOfferte, NltOfferteClick.id_offerta == NltOfferte.id_offerta)\
         .join(User, NltOfferteClick.id_dealer == User.id)

        if admin_id:
            query = query.filter(User.parent_id == admin_id)

        query = query.group_by(
            NltOfferteClick.id_offerta,
            NltOfferte.marca,
            NltOfferte.modello,
            NltOfferte.versione,
            NltOfferte.solo_privati,        # ✅ AGGIUNGI QUI

            User.id,
            User.ragione_sociale
        ).order_by(desc("totale_click"))

        return [
            {
                "id_offerta": r.id_offerta,
                "marca": r.marca,
                "modello": r.modello,
                "versione": r.versione,
                "totale_click": r.totale_click,
                "dealer_id": r.dealer_id,
                "solo_privati": r.solo_privati,
                "dealer_ragione_sociale": r.ragione_sociale
            }
            for r in query.all()
        ]

    else:
        dealer_id = get_dealer_id(current_user)

        query = db.query(
            NltOfferteClick.id_offerta,
            func.count().label("totale_click"),
            NltOfferte.marca,
            NltOfferte.modello,
            NltOfferte.versione,
            NltOfferte.solo_privati
        ).join(NltOfferte, NltOfferteClick.id_offerta == NltOfferte.id_offerta)\
         .filter(NltOfferteClick.id_dealer == dealer_id)\
         .group_by(
             NltOfferteClick.id_offerta,
             NltOfferte.marca,
             NltOfferte.modello,
             NltOfferte.versione
         ).order_by(desc("totale_click"))

        return [
        {
            "id_offerta": r.id_offerta,
            "marca": r.marca,
            "modello": r.modello,
            "versione": r.versione,
            "totale_click": r.totale_click,
            "solo_privati": r.solo_privati
        }
        for r in query.all()
    ]


@router.get("/clicks-giornalieri")
def clicks_giornalieri(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    from app.auth_helpers import get_dealer_id, get_admin_id, is_admin_user

    oggi = datetime.utcnow().date()
    inizio = oggi - timedelta(days=13)

    if is_admin_user(current_user):
        admin_id = get_admin_id(current_user)

        # Click per giorno e dealer
        query = db.query(
            cast(NltOfferteClick.clicked_at, Date).label("giorno"),
            NltOfferteClick.id_dealer,
            User.ragione_sociale,
            func.count().label("click")
        ).join(User, NltOfferteClick.id_dealer == User.id)\
         .filter(NltOfferteClick.clicked_at >= inizio)

        if admin_id:
            query = query.filter(User.parent_id == admin_id)

        query = query.group_by("giorno", NltOfferteClick.id_dealer, User.ragione_sociale)\
                     .order_by("giorno")

        return [
            {
                "giorno": str(r.giorno),
                "click": r.click,
                "dealer_id": r.id_dealer,
                "dealer_ragione_sociale": r.ragione_sociale
            }
            for r in query.all()
        ]

    else:
        dealer_id = get_dealer_id(current_user)

        query = db.query(
            cast(NltOfferteClick.clicked_at, Date).label("giorno"),
            func.count().label("click")
        ).filter(
            NltOfferteClick.clicked_at >= inizio,
            NltOfferteClick.id_dealer == dealer_id
        ).group_by("giorno").order_by("giorno")

        return [
            {"giorno": str(r.giorno), "click": r.click}
            for r in query.all()
        ]

@router.get("/offerte-piu-cliccate-global")
def offerte_piu_cliccate_global(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        if not is_admin_user(current_user):
            raise HTTPException(status_code=403, detail="Solo gli admin possono accedere a questa statistica")

        admin_id = get_admin_id(current_user)
        print("🔎 admin_id:", admin_id)

        query = db.query(
            NltOfferte.marca,
            NltOfferte.modello,
            NltOfferte.versione,
            NltOfferte.solo_privati,
            func.count(NltOfferteClick.id).label("totale_click")
        ).join(NltOfferte, NltOfferteClick.id_offerta == NltOfferte.id_offerta)

        if admin_id:
            query = query.filter(NltOfferte.id_admin == admin_id)

        query = query.group_by(
            NltOfferte.marca,
            NltOfferte.modello,
            NltOfferte.versione,
            NltOfferte.solo_privati
        ).order_by(desc("totale_click"))

        risultati = query.all()
        print(f"✅ Totale offerte aggregate: {len(risultati)}")

        return [
            {
                "marca": r.marca,
                "modello": r.modello,
                "versione": r.versione,
                "solo_privati": bool(r.solo_privati),
                "totale_click": int(r.totale_click)
            }
            for r in risultati
        ]

    except Exception as e:
        print("❌ Errore in /offerte-piu-cliccate-global:", repr(e))
        raise HTTPException(status_code=500, detail="Errore interno")


@router.get("/clicks-per-dealer")
def clicks_per_dealer(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        if not is_admin_user(current_user):
            raise HTTPException(status_code=403, detail="Solo gli admin possono accedere a questa statistica")

        admin_id = get_admin_id(current_user)
        print("🔎 admin_id:", admin_id)

        query = db.query(
            User.id.label("dealer_id"),
            User.ragione_sociale,
            func.count(NltOfferteClick.id).label("totale_click")
        ).join(User, NltOfferteClick.id_dealer == User.id)

        if admin_id:
            query = query.filter(User.parent_id == admin_id)

        query = query.group_by(User.id, User.ragione_sociale).order_by(desc("totale_click"))

        risultati = query.all()
        print(f"✅ Totale dealer trovati: {len(risultati)}")

        return [
            {
                "dealer_id": int(r.dealer_id),
                "dealer_ragione_sociale": r.ragione_sociale or "—",
                "totale_click": int(r.totale_click)
            }
            for r in risultati
        ]

    except Exception as e:
        print("❌ Errore in /clicks-per-dealer:", repr(e))
        raise HTTPException(status_code=500, detail="Errore interno")
