from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.orm import Session
from typing import Optional, List
from app.database import get_db
from app.models import NltOfferte, NltQuotazioni, NltPlayers, NltImmagini, NltOfferteTag, NltOffertaTag, User, NltOffertaAccessori
from app.auth_helpers import is_admin_user, is_dealer_user, get_admin_id, get_dealer_id
from app.routes.nlt import get_current_user  
from datetime import date, datetime

router = APIRouter(
    prefix="/nlt/offerte",
    tags=["nlt-offerte"]
)

# Verifica ruolo admin o superadmin per inserire/modificare
def verify_admin_or_superadmin(user: User):
    if user.role not in ['admin', 'superadmin']:
        raise HTTPException(status_code=403, detail="Permessi insufficienti.")

# ✅ GET Offerte disponibili (dealer vede le offerte del proprio admin, admin le proprie, superadmin tutte)
@router.get("/")
async def get_offerte(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    attivo: Optional[bool] = Query(None)
):
    query = db.query(NltOfferte)

    if is_admin_user(current_user):
        query = query.filter(NltOfferte.id_admin == current_user.id)
    elif is_dealer_user(current_user):
        admin_id = get_admin_id(current_user)
        query = query.filter(NltOfferte.id_admin == admin_id)

    if attivo is not None:
        query = query.filter(NltOfferte.attivo == attivo)

    offerte = query.order_by(NltOfferte.data_inserimento.desc()).all()
    return {"success": True, "offerte": offerte}

@router.post("/")
async def crea_offerta(
    marca: str = Body(...),
    modello: str = Body(...),
    versione: str = Body(...),
    codice_motornet: str = Body(...),
    id_player: int = Body(...),
    prezzo_listino: Optional[float] = Body(None),
    prezzo_accessori: Optional[float] = Body(None),
    prezzo_mss: Optional[float] = Body(None),
    prezzo_totale: Optional[float] = Body(None),
    accessori: Optional[List[dict]] = Body(None),
    tags: Optional[List[int]] = Body(None),
    descrizione_breve: Optional[str] = Body(None),
    valido_da: Optional[str] = Body(None),
    valido_fino: Optional[str] = Body(None),
    quotazioni: Optional[dict] = Body(None),
    current_user: User = Depends(get_current_user),
    img_url: Optional[str] = None,
    db: Session = Depends(get_db)
):
    verify_admin_or_superadmin(current_user)

    if not valido_da:
        valido_da = datetime.utcnow().date()

    nuova_offerta = NltOfferte(
        id_admin=current_user.id,
        marca=marca,
        modello=modello,
        versione=versione,
        codice_motornet=codice_motornet,
        id_player=id_player,
        descrizione_breve=descrizione_breve,
        valido_da=valido_da,
        valido_fino=valido_fino,
        prezzo_listino=prezzo_listino,
        prezzo_accessori=prezzo_accessori,
        prezzo_mss=prezzo_mss,
        prezzo_totale=prezzo_totale
    )

    db.add(nuova_offerta)
    db.commit()
    db.refresh(nuova_offerta)

    # Accessori
    if accessori:
        for acc in accessori:
            nuovo = NltOffertaAccessori(
                id_offerta=nuova_offerta.id_offerta,
                codice=acc["codice"],
                descrizione=acc["descrizione"],
                prezzo=acc["prezzo"]
            )
            db.add(nuovo)

    # Tags
    if tags:
        for id_tag in tags:
            db.add(NltOffertaTag(
                id_offerta=nuova_offerta.id_offerta,
                id_tag=id_tag
            ))

    # Quotazioni
    if quotazioni:
        db.add(NltQuotazioni(
            id_offerta=nuova_offerta.id_offerta,
            mesi_36_10=quotazioni.get("36_10"),
            mesi_36_15=quotazioni.get("36_15"),
            mesi_36_20=quotazioni.get("36_20"),
            mesi_36_25=quotazioni.get("36_25"),
            mesi_36_30=quotazioni.get("36_30"),
            mesi_36_40=quotazioni.get("36_40"),
            mesi_48_10=quotazioni.get("48_10"),
            mesi_48_15=quotazioni.get("48_15"),
            mesi_48_20=quotazioni.get("48_20"),
            mesi_48_25=quotazioni.get("48_25"),
            mesi_48_30=quotazioni.get("48_30"),
            mesi_48_40=quotazioni.get("48_40")
        ))

    db.commit()

    if img_url:
        immagine_principale = NltImmagini(
            id_offerta=nuova_offerta.id_offerta,
            url_imagin=img_url,
            principale=True
        )
    db.add(immagine_principale)


    return {"success": True, "id_offerta": nuova_offerta.id_offerta}


# ✅ PUT Attiva/Disattiva Offerta
@router.put("/{id_offerta}/stato")
async def cambia_stato_offerta(
    id_offerta: int,
    attivo: bool,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    verify_admin_or_superadmin(current_user)

    offerta = db.query(NltOfferte).filter(NltOfferte.id_offerta == id_offerta).first()
    if not offerta:
        raise HTTPException(status_code=404, detail="Offerta non trovata.")

    if current_user.role != 'superadmin' and offerta.id_admin != current_user.id:
        raise HTTPException(status_code=403, detail="Non puoi modificare questa offerta.")

    offerta.attivo = attivo
    db.commit()
    db.refresh(offerta)

    return {"success": True, "attivo": offerta.attivo}

# ✅ GET Players disponibili (utile per frontend dropdown)
@router.get("/players")
async def get_players(db: Session = Depends(get_db)):
    players = db.query(NltPlayers).order_by(NltPlayers.nome).all()
    return {"success": True, "players": players}

# ✅ GET Tag disponibili (utile per frontend dropdown)
@router.get("/tags")
async def get_tags(db: Session = Depends(get_db)):
    tags = db.query(NltOfferteTag).order_by(NltOfferteTag.nome).all()
    return {"success": True, "tags": tags}

