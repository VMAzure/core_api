# app/routes/openai_config.py

from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi_jwt_auth import AuthJWT
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.database import get_db, supabase_client
from app.models import User, PurchasedServices, Services, CreditTransaction
from app.auth_helpers import is_admin_user, is_dealer_user
from app.routes.notifiche import inserisci_notifica
from app.openai_utils import genera_descrizione_gpt

from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session
import json


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
LEONARDO_WEBHOOK_SECRET = os.getenv("LEONARDO_WEBHOOK_SECRET", "")


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
    "low fidelity, low quality, blurry, noisy, distorted, "
    "inaccurate proportions, wrong branding, off-model, "
    "warped grille, deformed wheels, broken headlights, "
    "unnatural motion, jerky or fast racing motion, "
    "driving backwards, reverse gear, rear view, back view, "
    "car sliding sideways without reason, floating car, "
    "car bouncing unrealistically, car stretching or bending, "
    "camera jitter, sudden zooms, unnatural camera shake, "
    "frame skipping, inconsistent lighting, "
    "wrong reflections, mirrored logos, incorrect license plates, "
    "extra tires, extra headlights, duplicated parts, "
    "ghosting, double exposure, artifacts, "
    "text, captions, subtitles, watermark, logo artifacts, UI overlays, "
    "aliasing, pixelation, heavy compression, "
    "oversaturated colors, videogame graphics, cartoonish style, cgi look, "
    "plastic rendering, toon shading, unrealistic render, "
    "hyper saturation, unrealistic neon lighting with glow halos, "
    "Chinese characters, Asian text, foreign writing"
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
    storage_path: Optional[str] = None   # ← aggiungi = None
    public_url: Optional[str]

def _assert_env():
    if not LEONARDO_API_KEY:
        raise HTTPException(500, "LEONARDO_API_KEY mancante")
    # Supabase è già configurato in app.database (supabase_client)

def _build_prompt(marca: str, modello: str, anno: int, colore: Optional[str], allestimento: Optional[str] = None) -> str:
    colore_txt = f" {colore}" if colore else ""
    anno_txt = f" {anno}" if anno else ""
    allest_txt = f" {allestimento}" if allestimento else ""
    base = f"{marca} {modello}{allest_txt}{anno_txt}{colore_txt}"
    return (
        f"Generate a cinematic video of a {base}. "
        "Keep proportions, design and color factory-accurate. "
        "Place the car in a modern urban night setting with neon lights and reflections on wet asphalt. "
        "The car moves slowly forward while the camera orbits smoothly around it, showing close-up details "
        "and a three-quarter front view (front and side visible). "
        "Realistic style, cinematic quality, modern atmosphere, dynamic but natural motion. "
        "No text, no subtitles, no Chinese or foreign characters visible."
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
            "resolution": "RESOLUTION_720",
            "model": "MOTION2"
        }
    elif model == "MOTIONFAST":
        data = {
            "prompt": prompt,
            "resolution": "RESOLUTION_720",
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

async def _leonardo_fetch_job_once(client: httpx.AsyncClient, generation_id: str) -> tuple[str, list[str]]:
    r = await client.get(f"{LEONARDO_BASE_URL}/generations/{generation_id}")
    if r.status_code >= 300:
        raise HTTPException(status_code=502, detail=f"Leonardo status error: {r.text}")
    j = r.json()
    job = j.get("sdGenerationJob") or j.get("motionVideoGenerationJob") or {}
    status = (job.get("status") or "").lower()
    assets = job.get("videoAssets") or []
    urls = []
    for a in assets:
        u = a.get("url") or a.get("downloadUrl") or a.get("contentUrl")
        if u:
            urls.append(u)
    return status, urls


@router.post("/openai/video-hero", response_model=VideoHeroResponse, tags=["OpenAI"])
async def genera_video_hero_openai(
    payload: VideoHeroRequest,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    _assert_env()
    Authorize.jwt_required()

    # 1. Autenticazione utente
    user_email = Authorize.get_jwt_subject()
    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(403, "Utente non trovato")

    dealer = is_dealer_user(user)
    if dealer and (user.credit is None or user.credit < LEONARDO_CREDIT_COST):
        raise HTTPException(402, "Credito insufficiente")

    # 2. Lookup auto
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
    allestimento = (getattr(det, "allestimento", None) or "").strip() if det else None
    anno = int(getattr(auto, "anno_immatricolazione", 0) or 0)
    colore = (getattr(auto, "colore", None) or "").strip()

    if not (marca and modello and anno > 0):
        raise HTTPException(422, "Marca/Modello/Anno non disponibili")

    # 3. Prompt finale
    prompt = (
        f"{payload.scenario.strip()} "
        f"The vehicle is a {marca} {modello} {allestimento or ''} {anno} in {colore}. "
        "Keep proportions, design and color factory-accurate. "
        "No text, no subtitles, no Chinese or foreign characters visible."
    ) if payload.scenario else (
        payload.prompt_override or _build_prompt(marca, modello, anno, colore, allestimento)
    )

    # 4. Crea record DB
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
        user_id=user.id 
    )

    db.add(rec)
    db.commit()
    db.refresh(rec)

    # 5. Crea job su Leonardo
    headers = {"Authorization": f"Bearer {LEONARDO_API_KEY}"}
    try:
        async with httpx.AsyncClient(timeout=60, headers=headers) as client:
            gen_id = await _leonardo_text_to_video(client, prompt=prompt, req=payload)
    except Exception as e:
        rec.status = "failed"
        rec.error_message = str(e)
        db.commit()
        raise

    # 6. Aggiorna con generation_id
    rec.generation_id = gen_id
    rec.status = "processing"
    db.commit()

    # 7. Risposta immediata
    return VideoHeroResponse(
        success=True,
        id_auto=payload.id_auto,
        leonardo_generation_id=gen_id,
        storage_path=None,
        public_url=None
    )



@router.post("/webhooks/leonardo", tags=["Webhooks"])
async def leonardo_webhook(req: Request, db: Session = Depends(get_db)):
    # 🔐 Auth Bearer
    auth_header = req.headers.get("authorization") or req.headers.get("Authorization") or ""
    if auth_header.strip() != f"Bearer {LEONARDO_WEBHOOK_SECRET}":
        print(f"[WEBHOOK] ❌ Authorization non valida: {auth_header}")
        raise HTTPException(status_code=401, detail="Authorization header non valido")

    # 🔍 Parse JSON
    try:
        body = await req.json()
        print("[WEBHOOK] ✅ Payload JSON ricevuto:")
        print(json.dumps(body, indent=2, ensure_ascii=False))
    except Exception as e:
        print("[WEBHOOK] ❌ Errore parsing JSON:", str(e))
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # 🎯 generationId
    gen_id = (
        body.get("generationId")
        or body.get("id")
        or body.get("sdGenerationJob", {}).get("generationId")
        or body.get("motionVideoGenerationJob", {}).get("generationId")
        or body.get("data", {}).get("generationId")
        or body.get("data", {}).get("object", {}).get("generationId")
        or body.get("data", {}).get("object", {}).get("id")
        or body.get("data", {}).get("object", {}).get("generations_by_pk", {}).get("generationId")
        or body.get("data", {}).get("object", {}).get("generations_by_pk", {}).get("id")
    )
    if not isinstance(gen_id, str) or not gen_id:
        print("[WEBHOOK] ❌ generationId mancante nel payload.")
        raise HTTPException(status_code=400, detail="generationId mancante")

    # 🔎 Lookup
    rec = db.query(UsatoLeonardo).filter(UsatoLeonardo.generation_id == gen_id).first()
    if not rec:
        print(f"[WEBHOOK] ⚠️ generationId {gen_id} non trovato nel DB.")
        return {"ok": True, "note": "generation_id non associato"}

    if rec.status == "completed" and rec.public_url:
        print(f"[WEBHOOK] 🔁 generationId {gen_id} già completato.")
        return {"ok": True, "status": "already_completed", "public_url": rec.public_url}

    # 🎞️ Asset dal payload (preferito) o fetch
    asset_url = (
        body.get("motionMP4URL")
        or body.get("data", {}).get("object", {}).get("motionMP4URL")
        or body.get("data", {}).get("object", {}).get("generations_by_pk", {}).get("motionMP4URL")
        or body.get("data", {}).get("object", {}).get("motionGIFURL")
        or body.get("data", {}).get("object", {}).get("generations_by_pk", {}).get("motionGIFURL")
    )

    headers = {"Authorization": f"Bearer {LEONARDO_API_KEY}"}
    async with httpx.AsyncClient(timeout=120, headers=headers) as client:
        if asset_url:
            blob = await _download(client, asset_url)
        else:
            try:
                status, urls = await _leonardo_fetch_job_once(client, gen_id)
            except Exception as e:
                print(f"[WEBHOOK] ❌ Errore fetch Leonardo: {str(e)}")
                raise HTTPException(status_code=502, detail="Errore recupero job da Leonardo")

            if status in {"failed", "error"}:
                rec.status = "failed"
                rec.error_message = "Leonardo: job failed (webhook)"
                db.commit()
                return {"ok": True, "status": "failed"}

            if status not in {"completed", "succeeded", "finished"}:
                return {"ok": True, "status": status}

            if not urls:
                rec.status = "failed"
                rec.error_message = "Leonardo: nessun asset video (webhook)"
                db.commit()
                return {"ok": True, "status": "no_assets"}

            asset_url = _prefer_mp4(urls)
            blob = await _download(client, asset_url)

    # 📤 Upload su Supabase
    base = asset_url.split("?", 1)[0].lower()
    is_mp4 = base.endswith(".mp4")
    ext = ".mp4" if is_mp4 else ".webm"
    mime = "video/mp4" if is_mp4 else "video/webm"

    storage_path = f"{rec.id_auto}/{rec.id}{ext}"
    try:
        full_path, public_url = _sb_upload_and_sign(storage_path, blob, mime)
    except Exception as e:
        print(f"[WEBHOOK] ❌ Errore upload Supabase: {str(e)}")
        raise HTTPException(status_code=502, detail="Errore upload storage")

    # 🧾 Update DB (wrap corretto)
    try:
        rec.status = "completed"
        rec.storage_path = full_path
        rec.public_url = public_url
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[WEBHOOK] ❌ Errore commit DB (update rec): {str(e)}")
        raise HTTPException(status_code=500, detail="Errore salvataggio DB")

    # 💳 Addebito + notifica
    try:
        if rec.user_id and (rec.credit_cost or 0) > 0:
            dealer = db.query(User).filter(User.id == rec.user_id).first()
            if dealer and is_dealer_user(dealer):
                cost = float(rec.credit_cost or 0)
                dealer.credit = float(dealer.credit or 0) - cost
                db.add(CreditTransaction(
                    dealer_id=dealer.id,
                    amount=-cost,
                    transaction_type="USE",
                    note=f"Video hero Leonardo ({rec.model_id})"
                ))
                inserisci_notifica(
                    db=db,
                    utente_id=dealer.id,
                    tipo_codice="CREDITO_USATO",
                    messaggio=f"Hai utilizzato {cost:g} crediti per la generazione video."
                )
                db.commit()
    except Exception as e:
        db.rollback()
        print(f"[WEBHOOK] ⚠️ Errore addebito/notifica: {str(e)}")

    print(f"[WEBHOOK] ✅ Video completato, URL: {public_url}")
    return {"ok": True, "status": "completed", "public_url": public_url}
