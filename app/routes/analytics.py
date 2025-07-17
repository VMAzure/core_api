from fastapi import APIRouter, Depends, HTTPException, Request, Body, Header
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, cast, Date
from datetime import datetime, timedelta

from app.database import get_db
from app.models import NltOfferteClick, NltOfferte, User, NltVetrinaClick, SiteAdminSettings
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
    admin_id = get_admin_id(current_user)
    dealer_id = get_dealer_id(current_user)

    if is_admin_user(current_user):
        # Admin → offerte cliccate dove id_admin == mio ID
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
         .join(User, NltOfferteClick.id_dealer == User.id)\
         .filter(NltOfferte.id_admin == admin_id)\
         .group_by(
            NltOfferteClick.id_offerta,
            NltOfferte.marca,
            NltOfferte.modello,
            NltOfferte.versione,
            NltOfferte.solo_privati,
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
        # Dealer → offerte cliccate su offerte dove:
        # - il dealer è sé stesso
        # - oppure l’offerta è del suo admin
        query = db.query(
            NltOfferteClick.id_offerta,
            func.count().label("totale_click"),
            NltOfferte.marca,
            NltOfferte.modello,
            NltOfferte.versione,
            NltOfferte.solo_privati
        ).join(NltOfferte, NltOfferteClick.id_offerta == NltOfferte.id_offerta)\
         .filter(
            (NltOfferteClick.id_dealer == dealer_id) |
            (NltOfferte.id_admin == admin_id)
         )\
         .group_by(
            NltOfferteClick.id_offerta,
            NltOfferte.marca,
            NltOfferte.modello,
            NltOfferte.versione,
            NltOfferte.solo_privati
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
    oggi = datetime.utcnow().date()
    inizio = oggi - timedelta(days=13)

    admin_id = get_admin_id(current_user)
    dealer_id = get_dealer_id(current_user)

    # === Admin ===
    if is_admin_user(current_user):
        query = db.query(
            cast(NltOfferteClick.clicked_at, Date).label("giorno"),
            func.count().label("click")
        ).join(NltOfferte, NltOfferteClick.id_offerta == NltOfferte.id_offerta)\
         .filter(
             NltOfferteClick.clicked_at >= inizio,
             NltOfferte.id_admin == admin_id  # include offerte sue e dei suoi dealer
         )\
         .group_by("giorno").order_by("giorno")

        return [
            {"giorno": str(r.giorno), "click": int(r.click)}
            for r in query.all()
        ]

    # === Dealer ===
    else:
        query = db.query(
            cast(NltOfferteClick.clicked_at, Date).label("giorno"),
            func.count().label("click")
        ).join(NltOfferte, NltOfferteClick.id_offerta == NltOfferte.id_offerta)\
         .filter(
             NltOfferteClick.clicked_at >= inizio,
             (NltOfferteClick.id_dealer == dealer_id) | (NltOfferte.id_admin == admin_id)
         )\
         .group_by("giorno").order_by("giorno")

        return [
            {"giorno": str(r.giorno), "click": int(r.click)}
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



from sqlalchemy import union_all, literal, select

@router.get("/clicks-per-dealer")
def clicks_per_dealer(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Solo gli admin possono accedere a questa statistica")

    admin_id = get_admin_id(current_user)

    # 👤 Click dell'admin come se fosse un dealer (solo su sue offerte, cliccate sulla sua vetrina)
    subq_admin = db.query(
        literal(admin_id).label("dealer_id"),
        literal(current_user.ragione_sociale or "Admin").label("ragione_sociale"),
        func.count(NltOfferteClick.id).label("totale_click")
    ).join(NltOfferte, NltOfferteClick.id_offerta == NltOfferte.id_offerta)\
     .filter(
         NltOfferte.id_admin == admin_id,
         NltOfferteClick.id_dealer == admin_id  # cliccate sulla vetrina dell’admin
     )

    # 👥 Click per tutti i dealer figli dell’admin
    subq_dealer = db.query(
        User.id.label("dealer_id"),
        User.ragione_sociale.label("ragione_sociale"),
        func.count(NltOfferteClick.id).label("totale_click")
    ).join(User, NltOfferteClick.id_dealer == User.id)\
     .filter(User.parent_id == admin_id)\
     .group_by(User.id, User.ragione_sociale)

    # 🔁 Unione
    union_query = subq_dealer.union_all(subq_admin).order_by(desc("totale_click"))

    risultati = union_query.all()
    return [
        {
            "dealer_id": int(r.dealer_id),
            "dealer_ragione_sociale": r.ragione_sociale or "—",
            "totale_click": int(r.totale_click)
        }
        for r in risultati
    ]



@router.get("/offerte-cliccate-per-dealer/{dealer_id}")
def offerte_cliccate_per_dealer(
    dealer_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    from app.auth_helpers import is_admin_user, get_admin_id

    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Solo gli admin possono accedere a questa statistica")

    admin_id = get_admin_id(current_user)

    # verifica che dealer richiesto sia valido
    if dealer_id == admin_id:
        # admin → deve vedere solo le sue offerte, cliccate sulla sua vetrina
        query = db.query(
            NltOfferteClick.id_offerta,
            NltOfferte.marca,
            NltOfferte.modello,
            NltOfferte.versione,
            NltOfferte.solo_privati,
            func.count().label("totale_click")
        ).join(NltOfferte, NltOfferteClick.id_offerta == NltOfferte.id_offerta)\
         .filter(
             NltOfferte.id_admin == admin_id,
             NltOfferteClick.id_dealer == admin_id
         )\
         .group_by(
             NltOfferteClick.id_offerta,
             NltOfferte.marca,
             NltOfferte.modello,
             NltOfferte.versione,
             NltOfferte.solo_privati
         ).order_by(desc("totale_click"))
    else:
        # dealer assegnato all’admin
        dealer = db.query(User).filter(User.id == dealer_id, User.parent_id == admin_id).first()
        if not dealer:
            raise HTTPException(status_code=403, detail="Dealer non autorizzato")

        query = db.query(
            NltOfferteClick.id_offerta,
            NltOfferte.marca,
            NltOfferte.modello,
            NltOfferte.versione,
            NltOfferte.solo_privati,
            func.count().label("totale_click")
        ).join(NltOfferte, NltOfferteClick.id_offerta == NltOfferte.id_offerta)\
         .filter(NltOfferteClick.id_dealer == dealer_id)\
         .group_by(
             NltOfferteClick.id_offerta,
             NltOfferte.marca,
             NltOfferte.modello,
             NltOfferte.versione,
             NltOfferte.solo_privati
         ).order_by(desc("totale_click"))

    risultati = query.all()
    return [
        {
            "id_offerta": r.id_offerta,
            "marca": r.marca,
            "modello": r.modello,
            "versione": r.versione,
            "solo_privati": bool(r.solo_privati),
            "totale_click": int(r.totale_click)
        }
        for r in risultati
    ]


@router.post("/click-vetrina")
async def registra_click_vetrina(
    dealer_slug: str = Body(...),
    evento: str = Body(default="visita"),
    user_agent: str = Header(default=None),
    request: Request = None,
    db: Session = Depends(get_db)
):
    # 1. Recupera impostazioni del dealer
    settings = db.query(SiteAdminSettings).filter(SiteAdminSettings.slug == dealer_slug).first()
    if not settings:
        raise HTTPException(status_code=404, detail=f"Dealer '{dealer_slug}' non trovato.")
    id_dealer = settings.dealer_id or settings.admin_id

    # 2. Registra click vetrina
    click = NltVetrinaClick(
        id_dealer=id_dealer,
        evento=evento,
        user_agent=user_agent,
        ip=request.client.host,
        referrer=request.headers.get("referer")
    )
    db.add(click)
    db.commit()

    return {"success": True}


