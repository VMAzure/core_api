# app/routes/openai_config.py

from fastapi import APIRouter, HTTPException, Depends
from fastapi_jwt_auth import AuthJWT
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.database import get_db, supabase_client
from app.models import User, PurchasedServices, Services, CreditTransaction
from app.auth_helpers import is_admin_user, is_dealer_user
from app.routes.notifiche import inserisci_notifica
from app.openai_utils import genera_descrizione_gpt



router = APIRouter()

GPT_COSTO_CREDITO = 0.5

class PromptRequest(BaseModel):
    prompt: str
    max_tokens: int = 300

@router.post("/openai/genera", tags=["OpenAI"])
async def genera_testo(
    payload: PromptRequest,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()
    user = db.query(User).filter(User.email == user_email).first()

    if not user:
        raise HTTPException(status_code=403, detail="Utente non trovato")

    is_dealer = is_dealer_user(user)
    is_admin = is_admin_user(user)

    # DEALER → verifica credito
    if is_dealer:
        if user.credit is None or user.credit < GPT_COSTO_CREDITO:
            raise HTTPException(status_code=402, detail="Credito insufficiente")

    # 🧠 Genera testo
    output = await genera_descrizione_gpt(payload.prompt, payload.max_tokens)

    # DEALER → scala credito + notifica
    if is_dealer:
        user.credit -= GPT_COSTO_CREDITO

        db.add(CreditTransaction(
            dealer_id=user.id,
            amount=-GPT_COSTO_CREDITO,
            transaction_type="USE",
            note="Generazione GPT"
        ))

        inserisci_notifica(
            db=db,
            utente_id=user.id,
            tipo_codice="CREDITO_USATO",
            messaggio="Hai utilizzato 0.5 crediti per la generazione di un testo GPT."
        )

    db.commit()

    return {"success": True, "output": output}


# --- VIDEO HERO LEONARDO (JWT + credito) -------------------------------------
import os
import asyncio
import httpx
from datetime import timedelta
from uuid import UUID as _UUID
from typing import Optional

from fastapi import HTTPException, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    User,
    CreditTransaction,
    AZLeaseUsatoAuto,
    MnetDettaglioUsato,     # se il nome reale differisce, sostituisci
    UsatoLeonardo,
)
from app.routes.notifiche import inserisci_notifica
from app.auth_helpers import is_admin_user, is_dealer_user
from fastapi_jwt_auth import AuthJWT

# === ENV / CONFIG ===
LEONARDO_API_KEY = os.getenv("LEONARDO_API_KEY", "")
LEONARDO_BASE_URL = os.getenv("LEONARDO_BASE_URL", "https://cloud.leonardo.ai/api/rest/v1")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET_LEONARDO", "leonardo-video")

def _sb_upload_and_sign(path: str, blob: bytes, content_type: str) -> tuple[str, str | None]:
    # Upload con upsert usando l’SDK già autenticato (supabase_client)
    supabase_client.storage.from_(SUPABASE_BUCKET).upload(
        path=path,
        file=blob,
        file_options={"content-type": content_type, "upsert": "true"}
    )
    # URL firmata 30 giorni
    res = supabase_client.storage.from_(SUPABASE_BUCKET).create_signed_url(
        path=path,
        expires_in=60 * 60 * 24 * 30
    )
    signed = res.get("signedURL") or res.get("signed_url") or res.get("signedUrl")
    if signed and signed.startswith("/storage"):
        base = os.getenv("SUPABASE_URL", "").rstrip("/")
        signed = f"{base}{signed}"
    return path, signed
# Costo crediti per Dealer (override da env)
LEONARDO_CREDIT_COST = float(os.getenv("LEONARDO_CREDIT_COST", "5.0"))

NEGATIVE = (
    "low fidelity, inaccurate proportions, wrong branding, deformed wheels, "
    "warped grille, extra headlights, motion glitches, text, watermark, logo artifacts, "
    "incorrect color, aliasing, heavy noise"
)

class VideoHeroRequest(BaseModel):
    id_auto: _UUID
    model_id: str = Field(default="veo-3")
    duration_seconds: int = Field(default=5, ge=2, le=10)
    fps: int = Field(default=24, ge=12, le=60)
    aspect_ratio: str = Field(default="16:9")
    seed: Optional[int] = None
    scenario: Optional[str] = None   # 👈 nuovo campo per la descrizione
    prompt_override: Optional[str] = None



class VideoHeroResponse(BaseModel):
    success: bool
    id_auto: _UUID
    leonardo_generation_id: str
    storage_path: str
    public_url: Optional[str]

def _assert_env():
    if not LEONARDO_API_KEY:
        raise HTTPException(500, "LEONARDO_API_KEY mancante")
    # Supabase è già configurato in app.database (supabase_client)

def _build_prompt(marca: str, modello: str, anno: int, colore: Optional[str]) -> str:
    c = f", color {colore}" if colore else ""
    base = f"{marca} {modello} {anno}{c}"
    return (
        f"Photorealistic studio hero video of a {base}. "
        "Precise factory proportions, trims and badging. 3/4 front angle. "
        "Cinematic soft key light and subtle rim light. Neutral seamless background. "
        "Tripod camera, no camera shake. 5-second clip suitable for website hero."
    )

def _prefer_mp4(urls: list[str]) -> str:
    """Ritorna l'URL mp4 se esiste, altrimenti il primo asset disponibile."""
    for u in urls:
        if ".mp4" in u.split("?")[0].lower():
            return u
    return urls[0]


async def _leonardo_text_to_video(client: httpx.AsyncClient, *, prompt: str, req: VideoHeroRequest) -> str:
    model = (req.model_id or "").upper()

    if model == "VEO3":
        data = {
            "prompt": prompt,
            "width": 1280,
            "height": 720,
            "resolution": "RESOLUTION_720",
            "model": "VEO3"
        }
    elif model == "VEO3FAST":
        data = {
            "prompt": prompt,
            "width": 1280,
            "height": 720,
            "resolution": "RESOLUTION_720",
            "model": "VEO3FAST"
        }
    elif model == "MOTION":
        data = {
            "prompt": prompt,
            "resolution": "RESOLUTION_480",
            "model": "MOTION2"
        }
    elif model == "MOTIONFAST":
        data = {
            "prompt": prompt,
            "resolution": "RESOLUTION_480",
            "model": "MOTION2FAST"
        }
    else:
        raise HTTPException(status_code=400, detail="model_id non valido. Usa 'VEO3', 'VEO3FAST', 'MOTION', 'MOTIONFAST'.")

    r = await client.post(f"{LEONARDO_BASE_URL}/generations-text-to-video", json=data)
    if r.status_code == 402:
        raise HTTPException(status_code=402, detail="Leonardo: crediti API insufficienti")
    if r.status_code >= 300:
        raise HTTPException(status_code=502, detail=f"Leonardo TTV error ({r.status_code}): {r.text}")

    resp = r.json()
    gen_id = (
        resp.get("sdGenerationJob", {}).get("generationId")
        or resp.get("motionVideoGenerationJob", {}).get("generationId")
        or resp.get("generationId")
        or resp.get("id")
    )
    if not gen_id:
        raise HTTPException(
            status_code=502,
            detail=f"Leonardo: generationId non trovato. Response: {resp}"
        )
    return gen_id




async def _leonardo_poll(client: httpx.AsyncClient, generation_id: str, timeout_s: int = 120) -> list[str]:
    """
    Polla lo stato di una generazione Leonardo finché non è completata o fallita.
    Ritorna la lista di URL degli asset video.
    """
    elapsed, step = 0, 2

    while elapsed <= timeout_s:
        r = await client.get(f"{LEONARDO_BASE_URL}/generations/{generation_id}")
        if r.status_code >= 300:
            raise HTTPException(status_code=502, detail=f"Leonardo status error: {r.text}")
        j = r.json()

        # estrai job per i due modelli
        job = (
            j.get("sdGenerationJob")
            or j.get("motionVideoGenerationJob")
            or {}
        )
        status = (job.get("status") or "").lower()

        if status in ("completed", "succeeded", "finished"):
            assets = (
                job.get("videoAssets")
                or j.get("videoAssets")
                or j.get("assets")
                or []
            )
            urls = []
            for a in assets:
                u = a.get("url") or a.get("downloadUrl") or a.get("contentUrl")
                if u:
                    urls.append(u)
            if not urls:
                maybe = j.get("imageUrl") or j.get("videoUrl")
                if maybe:
                    urls = [maybe]
            if not urls:
                raise HTTPException(status_code=502, detail="Leonardo: nessun asset video in risposta")
            return urls

        if status in ("failed", "error"):
            err_msg = job.get("error") or job.get("message") or "Leonardo: generazione fallita"
            raise HTTPException(status_code=502, detail=err_msg)

        # ancora in coda/elaborazione → aspetto
        await asyncio.sleep(step)
        elapsed += step

    raise HTTPException(status_code=504, detail="Timeout in attesa del video da Leonardo")


async def _download(client: httpx.AsyncClient, url: str) -> bytes:
    r = await client.get(url)
    if r.status_code >= 300:
        raise HTTPException(502, f"Download asset fallito: {r.text}")
    return r.content


@router.post("/openai/video-hero", response_model=VideoHeroResponse, tags=["OpenAI"])
async def genera_video_hero_openai(
    payload: VideoHeroRequest,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    _assert_env()
    Authorize.jwt_required()

    # utente
    user_email = Authorize.get_jwt_subject()
    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(403, "Utente non trovato")

    dealer = is_dealer_user(user)
    admin = is_admin_user(user)

    # dealer → verifica credito
    if dealer:
        if user.credit is None or user.credit < LEONARDO_CREDIT_COST:
            raise HTTPException(402, "Credito insufficiente")

    # lookup auto
    auto = db.query(AZLeaseUsatoAuto).filter(AZLeaseUsatoAuto.id == payload.id_auto).first()
    if not auto:
        raise HTTPException(404, "Auto non trovata")

    det = None
    if getattr(auto, "codice_motornet", None):
        det = db.query(MnetDettaglioUsato)\
                .filter(MnetDettaglioUsato.codice_motornet_uni == auto.codice_motornet)\
                .first()

    marca = (getattr(det, "marca_nome", None) or "").strip()
    modello = (getattr(det, "modello", None) or "").strip()
    anno = int(getattr(auto, "anno_immatricolazione", 0) or 0)
    colore = (getattr(auto, "colore", None) or "").strip()

    if not (marca and modello and anno > 0):
        raise HTTPException(422, "Marca/Modello/Anno non disponibili")

    if payload.scenario:
        color_txt = f" in {colore}" if colore else ""
        prompt = f"A cinematic {payload.scenario} of a {marca} {modello} {anno}{color_txt}."
    else:
        prompt = payload.prompt_override or _build_prompt(marca, modello, anno, colore)


    # crea record 'queued'
    rec = UsatoLeonardo(
        id_auto=payload.id_auto,
        provider="leonardo",
        generation_id=None,
        status="queued",
        prompt=prompt,
        negative_prompt=NEGATIVE,
        model_id=payload.model_id,
        duration_seconds=payload.duration_seconds,
        fps=payload.fps,
        aspect_ratio=payload.aspect_ratio,
        seed=payload.seed,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)

    headers = {"Authorization": f"Bearer {LEONARDO_API_KEY}"}

    try:
        # crea job su Leonardo
        async with httpx.AsyncClient(timeout=60, headers=headers) as client:
            gen_id = await _leonardo_text_to_video(client, prompt=prompt, req=payload)

            rec.generation_id = gen_id
            rec.status = "processing"
            db.commit()

            # 🔁 poll fino a completamento (supporta sia VEO3 che MOTION2)
            urls = await _leonardo_poll(client, gen_id, timeout_s=180)

            # scegli asset .mp4 se disponibile
            asset = _prefer_mp4(urls)

            # scarica asset binario
            blob = await _download(client, asset)

        # 📤 upload su Supabase
        ext = ".mp4" if ".mp4" in asset.split("?")[0].lower() else ".webm"
        storage_path = f"{payload.id_auto}/{rec.id}{ext}"
        full_path, public_url = _sb_upload_and_sign(
            storage_path, blob, "video/mp4" if ext == ".mp4" else "video/webm"
        )

        # ✅ aggiorna record in DB
        rec.status = "completed"
        rec.storage_path = full_path
        rec.public_url = public_url
        db.commit()
        db.refresh(rec)

        # 💳 addebito crediti SOLO se dealer e SOLO a successo
        if dealer and LEONARDO_CREDIT_COST > 0:
            user.credit = (user.credit or 0) - LEONARDO_CREDIT_COST
            db.add(CreditTransaction(
                dealer_id=user.id,
                amount=-LEONARDO_CREDIT_COST,
                transaction_type="USE",
                note=f"Video hero Leonardo ({payload.model_id})"
            ))
            inserisci_notifica(
                db=db,
                utente_id=user.id,
                tipo_codice="CREDITO_USATO",
                messaggio=f"Hai utilizzato {LEONARDO_CREDIT_COST:g} crediti per la generazione video."
            )
            db.commit()

        return VideoHeroResponse(
            success=True,
            id_auto=payload.id_auto,
            leonardo_generation_id=rec.generation_id or "",
            storage_path=rec.storage_path or "",
            public_url=rec.public_url,
        )


    except HTTPException as e:
        # marca come failed, non addebita
        rec.status = "failed"
        rec.error_message = str(e.detail) if hasattr(e, "detail") else str(e)
        db.commit()
        raise

    except Exception as ex:
        rec.status = "failed"
        rec.error_message = str(ex)
        db.commit()
        raise HTTPException(502, "Errore non previsto durante la generazione video")
