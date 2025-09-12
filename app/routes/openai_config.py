# app/routes/openai_config.py

from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi_jwt_auth import AuthJWT
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.database import get_db, supabase_client
from app.models import User, PurchasedServices, Services, CreditTransaction, ScenarioDealer
from app.auth_helpers import is_admin_user, is_dealer_user
from app.routes.notifiche import inserisci_notifica
from app.openai_utils import genera_descrizione_gpt
from typing import Optional, Any
from uuid import uuid4

from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session
import json
import requests
import re, unicodedata


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
async def genera_testo_old(
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
    start_image_url: Optional[str] = None  


class GeminiVideoStatusRequest(BaseModel):
    operation_id: str


class GeminiImageHeroRequest(BaseModel):
    id_auto: _UUID
    scenario: Optional[str] = None
    prompt_override: Optional[str] = None
    start_image_url: Optional[str] = None  


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
    usato_leonardo_id: _UUID
    generation_id: Optional[str] = None  # ✅ aggiunto


import base64

async def _fetch_image_base64_from_url(url: str) -> tuple[str, str]:
    """Scarica immagine da URL e restituisce (mime_type, base64string)."""
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(url)
        if r.status_code >= 300:
            raise HTTPException(502, f"Download immagine fallito: {r.text}")
        mime = r.headers.get("content-type", "image/png")
        b64 = base64.b64encode(r.content).decode("utf-8")
        return mime, b64


async def _gemini_start_video(prompt: str, start_image_url: Optional[str] = None) -> str:
    if not GEMINI_API_KEY:
        raise HTTPException(500, "GEMINI_API_KEY non configurata")

    url = "https://generativelanguage.googleapis.com/v1beta/models/veo-3.0-generate-preview:predictLongRunning"

    # build instance
    instance = {"prompt": prompt}

    if start_image_url:
        mime, b64 = await _fetch_image_base64_from_url(start_image_url)
        instance["image"] = {
            "mimeType": mime,
            "bytesBase64Encoded": b64
        }

    payload = {
        "instances": [instance],
        "parameters": {
            "aspectRatio": "16:9"
        }
    }

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            url,
            json=payload,
            headers={
                "x-goog-api-key": GEMINI_API_KEY,
                "Content-Type": "application/json"
            }
        )

    if r.status_code >= 300:
        raise HTTPException(r.status_code, f"Errore Gemini start: {r.text}")

    data = r.json()
    op_name = data.get("name")
    if not op_name:
        # log utile per debug
        logging.error("Gemini start response senza 'name': %s", json.dumps(data, ensure_ascii=False))
        raise HTTPException(502, f"Gemini: operation name mancante. Resp: {data}")

    return op_name



async def _fetch_image_base64_from_url(url: str) -> tuple[str, str]:
    """Scarica immagine da URL e restituisce (mime_type, base64string)."""
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(url)
        if r.status_code >= 300:
            raise HTTPException(502, f"Download immagine fallito: {r.text}")
        mime = r.headers.get("content-type", "image/png")
        b64 = base64.b64encode(r.content).decode("utf-8")
        return mime, b64

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

def _plate_text_from_user(user: User) -> str:
    name = (
        getattr(user, "ragione_sociale", None)
        or getattr(user, "nome", None)
        or (user.email.split("@")[0] if getattr(user, "email", None) else None)
        or "AZURE"
    )
    # ASCII upper, solo A-Z0-9, max 8
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^A-Z0-9]", "", s.upper())
    return (s[:8] or "AZURE")


def _gemini_build_prompt(
    marca: str, modello: str, anno: int, colore: Optional[str],
    allestimento: Optional[str] = None, plate_text: Optional[str] = None
) -> str:
    colore_txt = f" {colore}" if colore else ""
    anno_txt = f" {anno}" if anno else ""
    allest_txt = f" {allestimento}" if allestimento else ""
    base = f"{marca} {modello}{allest_txt}{anno_txt}{colore_txt}"
    plate = f'Show a visible license plate that reads "{plate_text}" in a racing-style font. ' if plate_text else ""
    return (
        f"Generate a cinematic video of a {base}. "
        "Keep proportions, design and color factory-accurate. "
        "Place the car in a modern urban setting at dusk with realistic lighting and reflections. "
        "Smooth orbiting camera, three-quarter front view, natural motion. "
        f"{plate}"
        "No overlaid text or subtitles, no non-Latin characters."
    )

async def _download_bytes(url: str) -> bytes:
    headers = {"x-goog-api-key": GEMINI_API_KEY}
    async with httpx.AsyncClient(timeout=180, follow_redirects=True) as client:
        r = await client.get(url, headers=headers)
        if r.status_code >= 400:
            raise HTTPException(502, f"Download video fallito: {r.text}")
        return r.content

import httpx


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

    plate_text = _plate_text_from_user(user)  # A–Z0–9, max 8

    # Costruzione prompt
    prompt = (
        f"{payload.scenario.strip()} "
        f"The vehicle is a {marca} {modello} {allestimento or ''} {anno} in {colore}. "
        "Keep proportions, design and color factory-accurate. "
        f'Show a visible license plate that reads \"{plate_text}\" in a racing-style font. '
        "No overlaid text or subtitles, no non-Latin characters."
    ) if payload.scenario else (
        payload.prompt_override or _gemini_build_prompt(
            marca, modello, anno, colore, allestimento, plate_text=plate_text
        )
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
    rec.media_type = "video"
    rec.mime_type = "video/mp4"

    db.add(rec)
    db.commit()
    db.refresh(rec)

    try:
        operation_id = await _gemini_start_video(prompt, payload.start_image_url)
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

async def _gemini_generate_image_sync(prompt: str, start_image_url: Optional[str] = None) -> bytes:
    _gemini_assert_api()
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image-preview:generateContent"

    parts = [{"text": prompt}]
    if start_image_url:
        mime, b64 = await _fetch_image_base64_from_url(start_image_url)
        parts.append({
            "inline_data": {
                "mime_type": mime,
                "data": b64
            }
        })

    payload = {"contents": [{"parts": parts}]}

    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(url, json=payload, headers={
            "x-goog-api-key": GEMINI_API_KEY,
            "Content-Type": "application/json"
        })
        if r.status_code >= 300:
            raise HTTPException(r.status_code, f"Errore Gemini image: {r.text}")

        data = r.json()

        # Estrai immagine
        parts = (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [])
        )
        for p in parts:
            inline = (
                p.get("inline_data")
                or p.get("inlineData")
                or p.get("inline")  # fallback
            )
            if inline and inline.get("data"):
                return base64.b64decode(inline["data"])

        raise HTTPException(502, f"Gemini image: nessuna immagine trovata. Resp: {data}")



@router.post("/veo3/image-hero", response_model=GeminiImageHeroResponse, tags=["Gemini VEO 3"])
async def genera_image_hero_veo3(
    payload: GeminiImageHeroRequest,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()
    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(403, "Utente non trovato")

    IMG_COST = float(os.getenv("GEMINI_IMG_CREDIT_COST", "1.5"))
    if is_dealer_user(user):
        if user.credit is None or user.credit < IMG_COST:
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

    # Prompt di fallback
    prompt = payload.prompt_override or _gemini_build_image_prompt(marca, modello, anno, colore, allestimento)

    _gemini_assert_api()

    rec = UsatoLeonardo(
        id_auto=payload.id_auto,
        provider="gemini",
        generation_id=None,
        status="queued",
        media_type="image",
        mime_type="image/png",
        prompt=prompt,
        negative_prompt=None,
        model_id="gemini-2.5-flash-image-preview",
        aspect_ratio="16:9",
        credit_cost=IMG_COST,
        user_id=user.id
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)

    try:
        img_bytes = await _gemini_generate_image_sync(prompt, payload.start_image_url)

        # Upload su Supabase
        ext = ".png"
        path = f"{str(rec.id_auto)}/{str(rec.id)}{ext}"
        _, signed_url = _sb_upload_and_sign(path, img_bytes, "image/png")

        rec.public_url = signed_url
        rec.storage_path = path
        rec.status = "completed"
        db.commit()

        if is_dealer_user(user):
            user.credit = float(user.credit or 0) - IMG_COST
            db.add(CreditTransaction(
                dealer_id=user.id,
                amount=-IMG_COST,
                transaction_type="USE",
                note="Immagine hero Gemini"
            ))
            inserisci_notifica(
                db=db,
                utente_id=user.id,
                tipo_codice="CREDITO_USATO",
                messaggio=f"Hai utilizzato {IMG_COST:g} crediti per la generazione immagine."
            )
            db.commit()

        return GeminiImageHeroResponse(
            success=True,
            id_auto=payload.id_auto,
            status="completed",
            public_url=signed_url,
            error_message=None,
            usato_leonardo_id=rec.id,
            generation_id=None
        )

    except Exception as e:
        db.rollback()
        rec.status = "failed"
        rec.error_message = str(e)
        db.commit()
        raise HTTPException(500, f"Errore generazione immagine: {str(e)}")




# ⛔ deprecato: lo lasciamo per compatibilità, ma risponde subito
class GeminiImageStatusRequest(BaseModel):
    generation_id: str  # ✅ nome corretto atteso dal controller
    usato_leonardo_id: Optional[str] = None


class GeminiImageStatusResponse(BaseModel):
    status: str  # "processing" | "completed" | "failed" | "not_found"
    public_url: Optional[str] = None
    error_message: Optional[str] = None
    usato_leonardo_id: Optional[str] = None




@router.post("/veo3/image-status", response_model=GeminiImageStatusResponse, tags=["Gemini Image"])
async def check_image_status(
    payload: GeminiImageStatusRequest,
    db: Session = Depends(get_db)
):
    # Supporta sia generation_id che usato_leonardo_id
    rec = None
    if payload.usato_leonardo_id:
        rec = db.query(UsatoLeonardo).filter(UsatoLeonardo.id == payload.usato_leonardo_id).first()
    if not rec and payload.generation_id:
        rec = db.query(UsatoLeonardo).filter(UsatoLeonardo.generation_id == payload.generation_id).first()

    if not rec:
        return GeminiImageStatusResponse(status="not_found", error_message="Record non trovato")

    if rec.status == "completed" and rec.public_url:
        return GeminiImageStatusResponse(
            status="completed",
            public_url=rec.public_url,
            usato_leonardo_id=str(rec.id)
        )
    if rec.status in {"failed", "error"}:
        return GeminiImageStatusResponse(
            status="failed",
            error_message=rec.error_message or "Errore generazione",
            usato_leonardo_id=str(rec.id)
        )
    return GeminiImageStatusResponse(status=rec.status or "processing", usato_leonardo_id=str(rec.id))








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
        VEO_COST = float(os.getenv("GEMINI_VEO3_CREDIT_COST", "5.0"))
        if user.credit is None or user.credit < VEO_COST:
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

    # 🔴 SOLO prompt_override
    prompt = payload.prompt_override or _gemini_build_prompt(marca, modello, anno, colore, allestimento)

    _gemini_assert_api()

    rec = UsatoLeonardo(
        id_auto=payload.id_auto,
        provider="gemini",
        generation_id=None,
        status="queued",
        media_type="video",
        mime_type="video/mp4",
        prompt=prompt,
        negative_prompt=None,
        model_id="veo-3.0",
        duration_seconds=None,
        fps=None,
        aspect_ratio="16:9",
        seed=None,
        credit_cost=os.getenv("GEMINI_VEO3_CREDIT_COST", None),
        user_id=user.id
    )
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




@router.post("/webhooks/leonardo", tags=["Gemini VEO 3"])
async def leonardo_webhook(payload: dict, db: Session = Depends(get_db)):
    # Estrai operation/generation id
    gen_id = payload.get("name") or payload.get("operation_id") or payload.get("generationId")
    if not gen_id:
        raise HTTPException(400, "generationId mancante")

    rec = db.query(UsatoLeonardo).filter(UsatoLeonardo.generation_id == gen_id).first()
    if not rec:
        raise HTTPException(404, "Record generazione non trovato")

    # Determina stato e URL asset
    op = payload.get("operation") or payload
    done = op.get("done") is True
    if not done:
        rec.status = "processing"
        db.commit()
        return {"ok": True}

    # Estrai URL video/immagine
    uri = _extract_video_uri(op)  # per immagini puoi avere un helper simile
    if not uri:
        rec.status = "failed"
        rec.error_message = "URI asset mancante"
        db.commit()
        return {"ok": True}

    # Scarica e carica su Supabase
    blob = await _download_bytes(uri)
    ext = ".mp4" if rec.media_type == "video" else ".png"
    path = f"{str(rec.id_auto)}/{str(rec.id)}{ext}"
    public_url = _sb_upload_and_sign(path, blob, "video/mp4" if rec.media_type == "video" else "image/png")

    rec.public_url = public_url
    rec.storage_path = path
    rec.status = "completed"
    db.commit()

    # Crediti e notifica (se desideri qui)
    # inserisci_notifica(...)

    return {"ok": True}


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


class ScenarioDealerRequest(BaseModel):
    titolo: Optional[str] = None
    descrizione: str
    tags: Optional[str] = None


@router.post("/scenario-dealer", tags=["Scenario Dealer"])
async def crea_scenario_dealer(
    payload: ScenarioDealerRequest,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    # Autenticazione
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()
    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(403, "Utente non trovato")

    # ✅ Inserisci record
    rec = ScenarioDealer(
        dealer_id=user.id,
        titolo=payload.titolo,
        descrizione=payload.descrizione,
        tags=payload.tags
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)

    return {
        "success": True,
        "id": str(rec.id),
        "titolo": rec.titolo,
        "descrizione": rec.descrizione,
        "tags": rec.tags,
        "created_at": rec.created_at.isoformat()
    }


@router.get("/scenario-dealer/miei", tags=["Scenario Dealer"])
async def lista_scenari_dealer(
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()
    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(403, "Utente non trovato")

    records = db.query(ScenarioDealer).filter(ScenarioDealer.dealer_id == user.id).order_by(ScenarioDealer.created_at.desc()).all()
    return [
        {
            "id": str(r.id),
            "titolo": r.titolo,
            "descrizione": r.descrizione,
            "tags": r.tags,
            "created_at": r.created_at.isoformat(),
            "updated_at": r.updated_at.isoformat() if r.updated_at else None
        }
        for r in records
    ]


class ScenarioDealerUpdateRequest(BaseModel):
    titolo: Optional[str] = None
    descrizione: Optional[str] = None
    tags: Optional[str] = None


@router.patch("/scenario-dealer/{id}", tags=["Scenario Dealer"])
async def aggiorna_scenario_dealer(
    id: UUID,
    payload: ScenarioDealerUpdateRequest,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()
    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(403, "Utente non trovato")

    rec = db.query(ScenarioDealer).filter(ScenarioDealer.id == id, ScenarioDealer.dealer_id == user.id).first()
    if not rec:
        raise HTTPException(404, "Scenario non trovato")

    if payload.titolo is not None:
        rec.titolo = payload.titolo
    if payload.descrizione is not None:
        rec.descrizione = payload.descrizione
    if payload.tags is not None:
        rec.tags = payload.tags

    db.commit()
    db.refresh(rec)
    return {"success": True, "id": str(rec.id)}


@router.delete("/scenario-dealer/{id}", tags=["Scenario Dealer"])
async def elimina_scenario_dealer(
    id: UUID,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()
    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(403, "Utente non trovato")

    rec = db.query(ScenarioDealer).filter(ScenarioDealer.id == id, ScenarioDealer.dealer_id == user.id).first()
    if not rec:
        raise HTTPException(404, "Scenario non trovato")

    db.delete(rec)
    db.commit()
    return {"success": True}


##ROTTA TEST per immagini download

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Optional
import io
from PIL import Image

class WebpImageRequest(BaseModel):
    prompt: str
    start_image_url: Optional[str] = None   # ora opzionale

@router.post("/veo3/image-webp", tags=["Gemini VEO 3"])
async def genera_image_webp(payload: WebpImageRequest):
    try:
        # Genera immagine con Gemini
        img_bytes = await _gemini_generate_image_sync(
            prompt=payload.prompt,
            start_image_url=payload.start_image_url
        )

        # Converti in .webp in memoria
        img = Image.open(io.BytesIO(img_bytes))
        buf = io.BytesIO()
        img.save(buf, format="WEBP", quality=90)
        buf.seek(0)

        # Ritorna file da scaricare
        return Response(
            content=buf.read(),
            media_type="image/webp",
            headers={
                "Content-Disposition": 'attachment; filename="output.webp"'
            }
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore generazione immagine: {e}")