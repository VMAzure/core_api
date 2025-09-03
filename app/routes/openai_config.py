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
from typing import Optional, Any
from uuid import uuid4

from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session
import json

import logging, json, os
GEMINI_DEBUG = os.getenv("GEMINI_DEBUG", "0") == "1"

def _log_op(op: dict):
    if GEMINI_DEBUG:
        try:
            logging.warning("[Gemini op]%s", json.dumps(op, ensure_ascii=False)[:12000])
        except Exception:
            logging.warning("[Gemini op]<non-serializzabile>")



router = APIRouter()

GPT_COSTO_CREDITO = 0.5

class PromptRequest(BaseModel):
    prompt: str
    max_tokens: int = 300
    temperature: float = 0.4
    model: Optional[str] = None
    web_research: bool = False



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

    # ——————————————————————————————————————
    # Scelta modello
    model = (
        "gpt-4o-search-preview" if payload.web_research
        else (payload.model or "gpt-4o")
    )

    # Costo per modello (USD) → puoi convertirlo in crediti come vuoi
    MODEL_COSTO_CREDITO = {
        "gpt-4o": 0.5,
        "gpt-4o-mini": 0.25,
        "gpt-4o-search-preview": 0.75,  # ↑ browsing + citazioni
        "gpt-4o-mini-search-preview": 0.4
    }

    costo_credito = MODEL_COSTO_CREDITO.get(model, 0.5)

    # DEALER: verifica credito
    if is_dealer:
        if user.credit is None or user.credit < costo_credito:
            raise HTTPException(status_code=402, detail="Credito insufficiente")

    # ——————————————————————————————————————
    # Prompt LLM
    try:
        output = await genera_descrizione_gpt(
            prompt=payload.prompt,
            max_tokens=payload.max_tokens,
            temperature=payload.temperature,
            model=model,
            web_research=payload.web_research
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore LLM: {e}")

    # ——————————————————————————————————————
    # DEALER: scala credito e notifica
    if is_dealer:
        user.credit -= costo_credito

        db.add(CreditTransaction(
            dealer_id=user.id,
            amount=-costo_credito,
            transaction_type="USE",
            note=f"Generazione GPT ({model})"
        ))

        inserisci_notifica(
            db=db,
            utente_id=user.id,
            tipo_codice="CREDITO_USATO",
            messaggio=f"Hai utilizzato {costo_credito} crediti per la generazione GPT ({model})."
        )

        db.commit()

    return {"success": True, "output": output}


@router.post("/openai/genera_old", tags=["OpenAI"])
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


# --- VIDEO HERO GEMINI (JWT + credito) -------------------------------------
import os
import httpx
from uuid import UUID as _UUID
from typing import Optional

from pydantic import BaseModel
import google.generativeai as genai

from fastapi import HTTPException, Depends
from sqlalchemy.orm import Session
from fastapi_jwt_auth import AuthJWT

from app.models import User, CreditTransaction, AZLeaseUsatoAuto, MnetDettaglioUsato, UsatoLeonardo
from app.routes.notifiche import inserisci_notifica
from app.auth_helpers import is_dealer_user

# ENV
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET_LEONARDO", "leonardo-video")
GEMINI_VEO3_CREDIT_COST = float(os.getenv("GEMINI_VEO3_CREDIT_COST", "5.0"))

# NB: riusa _sb_upload_and_sign(path, blob, content_type) già definita nel file.

class GeminiVideoHeroRequest(BaseModel):
    id_auto: _UUID
    scenario: Optional[str] = None
    prompt_override: Optional[str] = None



class GeminiVideoStatusRequest(BaseModel):
    operation_id: str

class GeminiImageHeroRequest(BaseModel):
    id_auto: _UUID
    scenario: Optional[str] = None
    prompt_override: Optional[str] = None


# --- VIDEO VEO3 ---
class GeminiVideoHeroResponse(BaseModel):
    success: bool
    id_auto: _UUID
    gemini_operation_id: str
    status: str
    usato_leonardo_id: _UUID  # ← aggiunto

class GeminiVideoStatusResponse(BaseModel):
    status: str
    public_url: Optional[str] = None
    error_message: Optional[str] = None
    usato_leonardo_id: Optional[_UUID] = None  # ← opzionale, utile al FE

# --- IMAGE ---
class GeminiImageHeroResponse(BaseModel):
    success: bool
    id_auto: _UUID
    status: str
    public_url: Optional[str] = None
    error_message: Optional[str] = None
    usato_leonardo_id: _UUID  # ← aggiunto



def _extract_video_uri(op: dict):
    resp = op.get("response") or {}
    for key in ("generatedVideos","videos","videoPreviews","previews","outputs","assets"):
        arr = resp.get(key)
        if isinstance(arr, list) and arr:
            v0 = arr[0] if isinstance(arr[0], dict) else None
            if v0:
                uri = (
                    v0.get("uri")
                    or v0.get("videoUri")
                    or (v0.get("video") or {}).get("uri")
                    or (v0.get("asset") or {}).get("uri")
                    or (v0.get("content") or {}).get("uri")
                    or v0.get("url")
                )
                if isinstance(uri, str):
                    return uri
    # fallback ricorsivo
    stack=[resp]
    while stack:
        cur=stack.pop()
        if isinstance(cur, dict):
            if isinstance(cur.get("uri"), str): return cur["uri"]
            if isinstance(cur.get("url"), str) and cur["url"].startswith(("http://","https://")): return cur["url"]
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)
    return None


def _gemini_assert_api():
    if not GEMINI_API_KEY:
        raise HTTPException(500, "GEMINI_API_KEY non configurata")
    genai.configure(api_key=GEMINI_API_KEY)

def _gemini_build_prompt(marca: str, modello: str, anno: int, colore: Optional[str], allestimento: Optional[str] = None) -> str:
    colore_txt = f" {colore}" if colore else ""
    anno_txt = f" {anno}" if anno else ""
    allest_txt = f" {allestimento}" if allestimento else ""
    base = f"{marca} {modello}{allest_txt}{anno_txt}{colore_txt}"
    return (
        f"Generate a cinematic video of a {base}. "
        "Keep proportions, design and color factory-accurate. "
        "Place the car in a modern urban setting at dusk with realistic lighting and reflections. "
        "Smooth orbiting camera, three-quarter front view, natural motion. "
        "No text, no subtitles, no non-Latin characters."
    )


async def _download_bytes(url: str) -> bytes:
    headers = {"x-goog-api-key": GEMINI_API_KEY}
    async with httpx.AsyncClient(timeout=180, follow_redirects=True) as client:
        r = await client.get(url, headers=headers)
        if r.status_code >= 400:
            raise HTTPException(502, f"Download video fallito: {r.text}")
        return r.content


import httpx

async def _gemini_start_video(prompt: str) -> str:
    if not GEMINI_API_KEY:
        raise HTTPException(500, "GEMINI_API_KEY non configurata")

    url = "https://generativelanguage.googleapis.com/v1beta/models/veo-3.0-generate-preview:predictLongRunning"
    payload = {
        "instances": [{
            "prompt": prompt
        }],
        "parameters": {
            "aspectRatio": "16:9"
            # opzionale: "negativePrompt": "...", "personGeneration": "allow_adult"
        }
    }

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            url,
            json=payload,
            headers={"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"},
        )
        if r.status_code >= 300:
            raise HTTPException(r.status_code, f"Errore Gemini: {r.text}")
        data = r.json()
        op_name = data.get("name")
        if not op_name:
            raise HTTPException(502, f"Gemini: operation name mancante. Resp: {data}")
        return op_name


async def _gemini_get_operation(op_name: str) -> dict:
    url = f"https://generativelanguage.googleapis.com/v1beta/{op_name}"
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(url, headers={"x-goog-api-key": GEMINI_API_KEY})
        if r.status_code >= 300:
            raise HTTPException(r.status_code, f"Errore polling Gemini: {r.text}")
        return r.json()



@router.post("/veo3/video-hero", response_model=GeminiVideoHeroResponse, tags=["Gemini VEO 3"])
async def genera_video_hero_veo3(
    payload: GeminiVideoHeroRequest,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()
    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(403, "Utente non trovato")

    if is_dealer_user(user):
        if user.credit is None or user.credit < GEMINI_VEO3_CREDIT_COST:
            raise HTTPException(402, "Credito insufficiente")

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

    prompt = (
        f"{payload.scenario.strip()} "
        f"The vehicle is a {marca} {modello} {allestimento or ''} {anno} in {colore}. "
        "Keep proportions, design and color factory-accurate. "
        "No text, no subtitles, no non-Latin characters."
    ) if payload.scenario else (
        payload.prompt_override or _gemini_build_prompt(marca, modello, anno, colore, allestimento)
    )

    _gemini_assert_api()

    rec = UsatoLeonardo(
        id_auto=payload.id_auto,
        provider="gemini",
        generation_id=None,
        status="queued",
        prompt=prompt,
        negative_prompt=None,
        model_id="veo-3.0",
        duration_seconds=None,
        fps=None,
        aspect_ratio="16:9",
        seed=None,
        user_id=user.id
    )

    # imposta attributi non presenti nel costruttore (solo se esistono nel modello DB)
    rec.media_type = "video"
    rec.mime_type = "video/mp4"
    # rec.credit_cost = GEMINI_IMG_CREDIT_COST  ← SOLO se esiste nel modello

    db.add(rec)
    db.commit()
    db.refresh(rec)

    try:
        operation_id = await _gemini_start_video(prompt)
    except Exception as e:
        rec.status = "failed"
        rec.error_message = str(e)
        db.commit()
        raise

    rec.generation_id = operation_id
    rec.status = "processing"
    db.commit()

    return GeminiVideoHeroResponse(
        success=True,
        id_auto=payload.id_auto,
        gemini_operation_id=operation_id,
        status="processing",
        usato_leonardo_id=rec.id  

    )

@router.post("/veo3/video-status", response_model=GeminiVideoStatusResponse, tags=["Gemini VEO 3"])
async def check_video_status(
    payload: GeminiVideoStatusRequest,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()
    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(403, "Utente non trovato")

    rec = db.query(UsatoLeonardo).filter(UsatoLeonardo.generation_id == payload.operation_id).first()
    if not rec:
        raise HTTPException(404, "Operazione non trovata nel database.")

    if rec.status == "completed" and rec.public_url:
        return GeminiVideoStatusResponse(status="completed", public_url=rec.public_url)

    _gemini_assert_api()

    try:
        op = await _gemini_get_operation(payload.operation_id)
    except Exception:
        # errore transitorio → non marchiare failed
        return GeminiVideoStatusResponse(
            status="processing",
            error_message="Errore temporaneo polling"
        )

    # op è un dict JSON dalla REST API
    if "error" in op:
        rec.status = "failed"
        rec.error_message = op["error"].get("message", "Generazione fallita")
        db.commit()
        return GeminiVideoStatusResponse(
            status="failed",
            error_message=rec.error_message
        )

    if not op.get("done", False):
        return GeminiVideoStatusResponse(status="processing")

    # risultato disponibile
    result = op.get("response", {})
    uri = None

    # Caso standard documented da Google
    vids = result.get("generatedVideos") or result.get("videos") or []
    if vids:
        v0 = vids[0]
        video_obj = v0.get("video") or {}
        uri = v0.get("uri") or video_obj.get("uri") or v0.get("videoUri")

    # ✅ Caso reale che hai ottenuto
    if not uri:
        generate_resp = result.get("generateVideoResponse", {})
        samples = generate_resp.get("generatedSamples") or []
        if samples:
            first = samples[0]
            video = first.get("video") or {}
            uri = video.get("uri")



    try:
        blob = await _download_bytes(uri)
        storage_path = f"{rec.id_auto}/{rec.id}.mp4"
        full_path, public_url = _sb_upload_and_sign(storage_path, blob, "video/mp4")

        rec.status = "completed"
        rec.storage_path = full_path
        rec.public_url = public_url
        rec.credit_cost = GEMINI_VEO3_CREDIT_COST
        db.commit()

        if is_dealer_user(user):
            user.credit = float(user.credit or 0) - GEMINI_VEO3_CREDIT_COST
            db.add(CreditTransaction(
                dealer_id=user.id,
                amount=-GEMINI_VEO3_CREDIT_COST,
                transaction_type="USE",
                note="Video hero Gemini VEO 3"
            ))
            inserisci_notifica(
                db=db,
                utente_id=user.id,
                tipo_codice="CREDITO_USATO",
                messaggio=f"Hai utilizzato {GEMINI_VEO3_CREDIT_COST:g} crediti per la generazione video."
            )
            db.commit()

        return GeminiVideoStatusResponse(status="completed", public_url=public_url)

    except Exception as e:
        db.rollback()
        rec.status = "failed"
        rec.error_message = f"Errore finalizzazione video: {str(e)}"
        db.commit()
        raise HTTPException(500, detail=rec.error_message)

# --- GEMINI IMAGE (start + status) ------------------------------------------
from uuid import UUID as _UUID
from typing import Optional
from pydantic import BaseModel

# --- GEMINI IMAGE (sincrona) -------------------------------------------------
GEMINI_IMG_CREDIT_COST = float(os.getenv("GEMINI_IMG_CREDIT_COST", "1.0"))



def _gemini_build_image_prompt(marca: str, modello: str, anno: int, colore: Optional[str], allestimento: Optional[str] = None) -> str:
    colore_txt = f" {colore}" if colore else ""
    anno_txt = f" {anno}" if anno else ""
    allest_txt = f" {allestimento}" if allestimento else ""
    base = f"{marca} {modello}{allest_txt}{anno_txt}{colore_txt}"
    return (
        f"Create a high-quality photo of a {base}. "
        "Factory-accurate proportions, design, color, branding. "
        "Luxury urban setting at dusk with realistic lighting and reflections. "
        "Three-quarter front view, crisp details, photographic realism. "
        "No text, no watermarks, no non-Latin characters."
    )

async def _gemini_generate_image_sync(prompt: str) -> bytes:
    _gemini_assert_api()
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image-preview:generateContent"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}]
    }
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(url, json=payload, headers={"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"})
        if r.status_code >= 300:
            raise HTTPException(r.status_code, f"Errore Gemini image: {r.text}")
        data = r.json()
        # Estrai la prima immagine da inline_data
        parts = (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [])
        )
        for p in parts:
            inline = p.get("inline_data") or p.get("inlineData")
            if inline and inline.get("data"):
                import base64
                return base64.b64decode(inline["data"])
        raise HTTPException(502, "Gemini image: nessuna immagine nel response")

@router.post("/veo3/image-hero", response_model=GeminiImageHeroResponse, tags=["Gemini Image"])
async def genera_image_hero(
    payload: GeminiImageHeroRequest,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()
    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(403, "Utente non trovato")

    if is_dealer_user(user) and (user.credit is None or user.credit < GEMINI_IMG_CREDIT_COST):
        raise HTTPException(402, "Credito insufficiente")

    auto = db.query(AZLeaseUsatoAuto).filter(AZLeaseUsatoAuto.id == payload.id_auto).first()
    if not auto:
        raise HTTPException(404, "Auto non trovata")

    det = None
    if getattr(auto, "codice_motornet", None):
        det = db.query(MnetDettaglioUsato).filter(MnetDettaglioUsato.codice_motornet_uni == auto.codice_motornet).first()

    marca = (getattr(det, "marca_nome", None) or "").strip()
    modello = (getattr(det, "modello", None) or "").strip()
    allestimento = (getattr(det, "allestimento", None) or "").strip() if det else None
    anno = int(getattr(auto, "anno_immatricolazione", 0) or 0)
    colore = (getattr(auto, "colore", None) or "").strip()
    if not (marca and modello and anno > 0):
        raise HTTPException(422, "Marca/Modello/Anno non disponibili")

    prompt = (
        f"Create a high-quality photo of a {marca} {modello} {allestimento or ''} {anno} in {colore}. "
        "Factory-accurate proportions, design, and color. "
        "Luxury urban setting at dusk with cinematic lighting and realistic reflections. "
        "Three-quarter front view. Wide horizontal composition (16:9). "
        "Photographic realism, crisp details, depth of field. "
        "No license plate, no text, no watermarks, no logos, no non-Latin characters."
    )


    # 1) genera immagine sincrona
    img_bytes = await _gemini_generate_image_sync(prompt)

    # 2) salva su storage
    storage_path = f"{payload.id_auto}/gemini-img-{os.urandom(4).hex()}.png"
    full_path, public_url = _sb_upload_and_sign(storage_path, img_bytes, "image/png")

    # 3) traccia su UsatoLeonardo
    rec = UsatoLeonardo(
        id_auto=payload.id_auto,
        provider="gemini-image",
        generation_id=f"sync-{uuid4()}",
        status="completed",
        prompt=prompt,
        negative_prompt=None,
        model_id="gemini-2.5-flash-image-preview",
        duration_seconds=None,
        fps=None,
        aspect_ratio="16:9",
        seed=None,
        user_id=user.id,
        media_type="image",
        mime_type="image/png",
        storage_path=full_path,
        public_url=public_url,
        credit_cost=GEMINI_IMG_CREDIT_COST,
    )
    db.add(rec)

    # 4) addebito se dealer
    if is_dealer_user(user):
        user.credit = float(user.credit or 0) - GEMINI_IMG_CREDIT_COST
        db.add(CreditTransaction(
            dealer_id=user.id,
            amount=-GEMINI_IMG_CREDIT_COST,
            transaction_type="USE",
            note="Immagine hero Gemini"
        ))
        inserisci_notifica(
            db=db,
            utente_id=user.id,
            tipo_codice="CREDITO_USATO",
            messaggio=f"Hai utilizzato {GEMINI_IMG_CREDIT_COST:g} crediti per la generazione immagine."
        )
    db.commit()

    return GeminiImageHeroResponse(success=True, id_auto=payload.id_auto, status="completed", public_url=public_url, usato_leonardo_id=rec.id)

# ⛔ deprecato: lo lasciamo per compatibilità, ma risponde subito
class GeminiImageStatusRequest(BaseModel):
    operation_id: str

class GeminiImageStatusResponse(BaseModel):
    status: str
    public_url: Optional[str] = None
    error_message: Optional[str] = None

@router.post("/veo3/image-status", response_model=GeminiImageStatusResponse, tags=["Gemini Image"])
async def check_image_status(
    payload: GeminiImageStatusRequest,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()

    rec = db.query(UsatoLeonardo).filter(
        UsatoLeonardo.provider == "gemini-image",
        UsatoLeonardo.generation_id == payload.operation_id
    ).first()

    if not rec:
        return GeminiImageStatusResponse(status="not_found", error_message="Operazione non trovata")

    if rec.status == "completed" and rec.public_url:
        return GeminiImageStatusResponse(status="completed", public_url=rec.public_url)

    if rec.status in {"failed", "error"}:
        return GeminiImageStatusResponse(status="failed", error_message=(rec.error_message or "Errore generazione"))

    return GeminiImageStatusResponse(status="processing")





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
    rec.media_type = "video"
    rec.mime_type = "video/mp4"

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

from uuid import UUID

@router.patch("/usato-leonardo/{id}/usa", tags=["Usato AI"])
def usa_hero_media(id: UUID, Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    rec = db.query(UsatoLeonardo).filter(UsatoLeonardo.id == id).first()
    if not rec:
        raise HTTPException(404, "Record non trovato")

    # Disattiva gli altri media dello stesso tipo per l’auto
    db.query(UsatoLeonardo).filter(
        UsatoLeonardo.id_auto == rec.id_auto,
        UsatoLeonardo.media_type == rec.media_type
    ).update({UsatoLeonardo.is_active: False})

    # Attiva questo
    rec.is_active = True
    db.commit()
    return {"success": True}

