# usato_vetrina.py

from fastapi import APIRouter, Depends, HTTPException, Body
from fastapi_jwt_auth import AuthJWT
from sqlalchemy.orm import Session
from sqlalchemy import text
from uuid import UUID

from app.database import get_db
from app.models import UsatoVetrina, User, SiteAdminSettings

from pydantic import BaseModel
from typing import Optional, List
import uuid

router = APIRouter(prefix="/usato", tags=["AZLease Vetrina"])


# === Schemi ===
class VetrinaCreate(BaseModel):
    media_type: str  # "foto" o "ai"
    media_id: UUID


class VetrinaUpdate(BaseModel):
    priority: Optional[int] = None


class VetrinaOut(BaseModel):
    id: UUID
    id_auto: UUID
    media_type: str
    media_id: UUID
    priority: Optional[int]
    created_at: Optional[str]

    class Config:
        orm_mode = True


# === Rotte ===

@router.get("/{id_auto}/vetrina", response_model=List[VetrinaOut])
def get_vetrina_auto(
    id_auto: UUID,
    db: Session = Depends(get_db)
):
    """Restituisce i media pubblicati in vetrina per una certa auto"""
    rows = (
        db.query(UsatoVetrina)
        .filter(UsatoVetrina.id_auto == id_auto)
        .order_by(UsatoVetrina.priority.asc().nullslast(),
                  UsatoVetrina.created_at.asc())
        .all()
    )
    return rows


@router.post("/{id_auto}/vetrina", response_model=VetrinaOut)
def add_media_vetrina(
    id_auto: UUID,
    data: VetrinaCreate,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    """Aggiunge un media alla vetrina (se non già presente)"""
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()
    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(401, "Utente non trovato")

    exists = (
        db.query(UsatoVetrina)
        .filter(UsatoVetrina.id_auto == id_auto,
                UsatoVetrina.media_type == data.media_type,
                UsatoVetrina.media_id == data.media_id)
        .first()
    )
    if exists:
        raise HTTPException(409, "Media già presente in vetrina")

    rec = UsatoVetrina(
        id=uuid.uuid4(),
        id_auto=id_auto,
        media_type=data.media_type,
        media_id=data.media_id,
        priority=None,
        created_by=user.id
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


@router.patch("/vetrina/{id}", response_model=VetrinaOut)
def update_media_vetrina(
    id: UUID,
    data: VetrinaUpdate,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    """Aggiorna la priorità di un media nella vetrina"""
    Authorize.jwt_required()
    rec = db.query(UsatoVetrina).filter(UsatoVetrina.id == id).first()
    if not rec:
        raise HTTPException(404, "Media vetrina non trovato")

    if data.priority is not None:
        rec.priority = data.priority

    db.commit()
    db.refresh(rec)
    return rec


@router.delete("/vetrina/{id}")
def delete_media_vetrina(
    id: UUID,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    """Rimuove un media dalla vetrina"""
    Authorize.jwt_required()
    rec = db.query(UsatoVetrina).filter(UsatoVetrina.id == id).first()
    if not rec:
        raise HTTPException(404, "Media vetrina non trovato")

    db.delete(rec)
    db.commit()
    return {"success": True, "deleted_id": str(id)}


@router.get("/{slug}/vetrina-cards")
def lista_vetrina_cards(slug: str, db: Session = Depends(get_db)):
    """
    Restituisce auto visibili con cover e count immagini vetrina
    per popolare le card nella lista pubblica.
    """
    # 1. Recupera impostazioni sito (admin o dealer)
    settings = db.query(SiteAdminSettings).filter(SiteAdminSettings.slug == slug).first()
    if not settings:
        raise HTTPException(404, f"Slug '{slug}' non trovato")

    admin_id = settings.admin_id
    dealer_id = settings.dealer_id

    # 2. Query: autos + cover + count
    query = text("""
        WITH v AS (
            SELECT v.id_auto,
                   v.media_type,
                   v.media_id,
                   v.priority,
                   ROW_NUMBER() OVER (
                       PARTITION BY v.id_auto
                       ORDER BY v.priority ASC NULLS LAST, v.created_at ASC
                   ) AS rn
            FROM usato_vetrina v
            JOIN azlease_usatoin i ON i.id = (SELECT id_usatoin FROM azlease_usatoauto a WHERE a.id = v.id_auto)
            WHERE i.visibile = TRUE
              AND (:dealer_id IS NULL OR i.dealer_id = :dealer_id)
              AND i.admin_id = :admin_id
        )
        SELECT
          a.id AS id_auto,
          d.marca_nome AS marca,
          d.allestimento,
          a.anno_immatricolazione,
          i.prezzo_vendita,
          i.iva_esposta,
          -- cover (priority 1 o più bassa)
          CASE v.media_type
            WHEN 'foto' THEN (SELECT foto FROM azlease_usatoimg WHERE id = v.media_id)
            WHEN 'ai'   THEN (SELECT public_url FROM usato_leonardo WHERE id = v.media_id)
          END AS cover_url,
          -- count totale immagini vetrina
          (SELECT COUNT(*) FROM usato_vetrina vv WHERE vv.id_auto = a.id) AS total_media
        FROM azlease_usatoauto a
        JOIN azlease_usatoin i ON i.id = a.id_usatoin
        LEFT JOIN mnet_dettagli_usato d ON d.codice_motornet_uni = a.codice_motornet
        LEFT JOIN v ON v.id_auto = a.id AND v.rn = 1
        WHERE i.visibile = TRUE
          AND (:dealer_id IS NULL OR i.dealer_id = :dealer_id)
          AND i.admin_id = :admin_id
        ORDER BY i.data_inserimento DESC
    """)

    rows = db.execute(query, {"dealer_id": dealer_id, "admin_id": admin_id}).mappings().all()

    return [dict(r) for r in rows]
