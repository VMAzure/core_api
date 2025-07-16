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
    current_user: dict = Depends(get_current_user)  # payload JWT con sub = email
):
    from app.auth_helpers import get_dealer_id, get_admin_id, is_admin_user

    user = db.query(User).filter(User.email == current_user["sub"]).first()
    if not user:
        raise HTTPException(status_code=401, detail="Utente non trovato")

    query = db.query(
        NltOfferteClick.id_offerta,
        func.count().label("totale_click"),
        NltOfferte.marca,
        NltOfferte.modello,
        NltOfferte.versione
    ).join(NltOfferte, NltOfferteClick.id_offerta == NltOfferte.id_offerta)

    if is_admin_user(user):
        admin_id = get_admin_id(user)
        if admin_id:
            query = query.filter(NltOfferte.id_admin == admin_id)
    else:
        dealer_id = get_dealer_id(user)
        query = query.filter(NltOfferteClick.id_dealer == dealer_id)

    query = query.group_by(
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
            "totale_click": r.totale_click
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

    query = db.query(
        cast(NltOfferteClick.clicked_at, Date).label("giorno"),
        func.count().label("click")
    ).filter(NltOfferteClick.clicked_at >= inizio)

    if is_admin_user(current_user):
        admin_id = get_admin_id(current_user)
        if admin_id:
            query = query.join(User, NltOfferteClick.id_dealer == User.id)\
                         .filter(User.parent_id == admin_id)
        # superadmin → no filtro
    else:
        dealer_id = get_dealer_id(current_user)
        query = query.filter(NltOfferteClick.id_dealer == dealer_id)

    query = query.group_by("giorno").order_by("giorno")

    return query.all()
