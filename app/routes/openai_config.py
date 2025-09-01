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
    payload = {
        "modelId": req.model_id,
        "prompt": prompt,
        "negativePrompt": NEGATIVE,
        "duration": req.duration_seconds,
        "fps": req.fps,
        "aspectRatio": req.aspect_ratio,
        "public": False,
    }
    if req.seed is not None:
        payload["seed"] = req.seed

    r = await client.post(f"{LEONARDO_BASE_URL}/generations-text-to-video", json=payload)
    if r.status_code >= 300:
        raise HTTPException(502, f"Leonardo TTV error: {r.text}")
    data = r.json()
    gen_id = (
        data.get("sdGenerationJob", {}).get("generationId")
        or data.get("generationId")
        or data.get("id")
    )
    if not gen_id:
        raise HTTPException(502, "Leonardo: generationId non trovato")
    return gen_id

async def _leonardo_poll(client: httpx.AsyncClient, generation_id: str, timeout_s: int = 120) -> list[str]:
    elapsed, step = 0, 2
    while elapsed <= timeout_s:
        r = await client.get(f"{LEONARDO_BASE_URL}/generations/{generation_id}")
        if r.status_code >= 300:
            raise HTTPException(502, f"Leonardo status error: {r.text}")
        j = r.json()
        status = (j.get("sdGenerationJob", {}).get("status") or j.get("status") or "").lower()
        if status in ("completed", "succeeded", "finished"):
            assets = (
                j.get("sdGenerationJob", {}).get("videoAssets")
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
                raise HTTPException(502, "Leonardo: nessun asset video")
            return urls
        if status in ("failed", "error"):
            raise HTTPException(502, j.get("error") or j.get("message") or "Leonardo: generazione fallita")
        await asyncio.sleep(step)
        elapsed += step
    raise HTTPException(504, "Timeout attesa video Leonardo")

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
        # crea job e poll
        async with httpx.AsyncClient(timeout=120, headers=headers) as client:
            gen_id = await _leonardo_text_to_video(client, prompt=prompt, req=payload)
            rec.generation_id = gen_id
            rec.status = "processing"
            db.commit()

            urls = await _leonardo_poll(client, gen_id, timeout_s=120)
            asset = _prefer_mp4(urls)
            blob = await _download(client, asset)

        # upload storage
        ext = ".mp4" if ".mp4" in asset.split("?")[0].lower() else ".webm"
        storage_path = f"{payload.id_auto}/{rec.id}{ext}"
        full_path, public_url = _sb_upload_and_sign(
            storage_path, blob, "video/mp4" if ext == ".mp4" else "video/webm"
        )


        # aggiorna record
        rec.status = "completed"
        rec.storage_path = full_path
        rec.public_url = public_url
        db.commit()
        db.refresh(rec)

        # addebito crediti SOLO dealer e SOLO a successo
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
