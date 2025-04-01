from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional, List
from app.database import get_db
from app.models import NltOfferte, NltQuotazioni, NltPlayers, NltImmagini, NltOfferteTag, NltOffertaTag, User
from app.auth_helpers import is_admin_user, is_dealer_user, get_admin_id, get_dealer_id
from app.routes.nlt import get_current_user  # Riutilizziamo l'autenticazione esistente

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

# ✅ POST Nuova offerta (solo admin o superadmin)
@router.post("/")
async def crea_offerta(
    marca: str,
    modello: str,
    versione: str,
    codice_motornet: str,
    id_player: int,
    descrizione_breve: Optional[str] = None,
    valido_da: Optional[str] = None,
    valido_fino: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    verify_admin_or_superadmin(current_user)

    nuova_offerta = NltOfferte(
        id_admin=current_user.id,
        marca=marca,
        modello=modello,
        versione=versione,
        codice_motornet=codice_motornet,
        id_player=id_player,
        descrizione_breve=descrizione_breve,
        valido_da=valido_da,
        valido_fino=valido_fino
    )

    db.add(nuova_offerta)
    db.commit()
    db.refresh(nuova_offerta)

    return {"success": True, "offerta": nuova_offerta}

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

