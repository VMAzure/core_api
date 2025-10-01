# app/routes/openai_config.py

# --- FastAPI / Auth / DB ---
from fastapi import APIRouter, HTTPException, Depends, Request, Response, UploadFile, File
from fastapi_jwt_auth import AuthJWT
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

# --- Utilità app interne ---
from app.database import get_db, supabase_client
from app.models import (
    User,
    PurchasedServices,
    Services,
    CreditTransaction,
    ScenarioDealer,
    AZLeaseUsatoAuto,
    MnetDettaglioUsato,
    UsatoLeonardo,
)
from app.auth_helpers import is_admin_user, is_dealer_user
from app.routes.notifiche import inserisci_notifica
from app.openai_utils import genera_descrizione_gpt

# --- Librerie standard ---
import os
import io
import re
import json
import base64
import asyncio
import logging
import requests
import unicodedata
from datetime import datetime, timedelta
from uuid import uuid4, UUID
from typing import Optional, Any
from uuid import UUID as _UUID
from io import BytesIO

# --- Librerie esterne ---
import httpx
import google.generativeai as genai
from PIL import Image
from openai import OpenAI


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



from typing import Union, List, Optional

class GeminiImageHeroRequest(BaseModel):
    id_auto: UUID
    scenario: Optional[str] = None
    prompt_override: Optional[str] = None
    start_image_url: Union[str, List[str], None] = None
    subject_image_url: Union[str, List[str], None] = None
    background_image_url: Union[str, List[str], None] = None



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



async def _fetch_image_base64_from_url(url: str) -> tuple[str, str]:
    """Scarica immagine da URL, ridimensiona a 1024x1024 e restituisce (mime_type, base64string)."""
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(url)
        if r.status_code >= 300:
            raise HTTPException(502, f"Download immagine fallito: {r.text}")
        mime = r.headers.get("content-type", "image/png")

        # Apri immagine e forza resize
        img = Image.open(BytesIO(r.content)).convert("RGB")
        img = img.resize((1024, 1024), Image.LANCZOS)

        buf = BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        return "image/png", b64


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
    marca: str,
    modello: str,
    anno: int,
    colore: Optional[str],
    allestimento: Optional[str] = None,
    plate_text: Optional[str] = None,
    precisazioni: Optional[str] = None   # 👈 nuovo
) -> str:
    colore_txt = f" {colore}" if colore else ""
    anno_txt = f" {anno}" if anno else ""
    allest_txt = f" {allestimento}" if allestimento else ""
    base = f"{marca} {modello}{allest_txt}{anno_txt}{colore_txt}"

    extra = f" Visual details: {precisazioni}." if precisazioni else ""
    plate = f'Show a visible license plate that reads "{plate_text}" in a racing-style font. ' if plate_text else ""

    return (
        f"Generate a cinematic video of a {base}. "
        "Keep proportions, design and color factory-accurate. "
        "Place the car in a modern urban setting at dusk with realistic lighting and reflections. "
        "Smooth orbiting camera, three-quarter front view, natural motion. "
        f"{extra}{plate}"
        "No overlaid text or subtitles, no non-Latin characters."
    )


async def _download_bytes(url: str) -> bytes:
    headers = {"x-goog-api-key": GEMINI_API_KEY}
    async with httpx.AsyncClient(timeout=180, follow_redirects=True) as client:
        r = await client.get(url, headers=headers)
        if r.status_code >= 400:
            raise HTTPException(502, f"Download video fallito: {r.text}")
        return r.content



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
        f"{'Visual details: ' + auto.precisazioni if auto.precisazioni else ''} "
        "No overlaid text or subtitles, no non-Latin characters."
    ) if payload.scenario else (
        payload.prompt_override or _gemini_build_prompt(
            marca, modello, anno, colore, allestimento,
            plate_text=plate_text,
            precisazioni=auto.precisazioni
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


# --- GEMINI IMAGE (sincrona) -------------------------------------------------
GEMINI_IMG_CREDIT_COST = float(os.getenv("GEMINI_IMG_CREDIT_COST", "1.0"))



def _gemini_build_image_prompt(
    marca: str,
    modello: str,
    anno: int,
    colore: Optional[str],
    allestimento: Optional[str] = None,
    precisazioni: Optional[str] = None   # 👈 nuovo
) -> str:
    colore_txt = f" {colore}" if colore else ""
    anno_txt = f" {anno}" if anno else ""
    allest_txt = f" {allestimento}" if allestimento else ""
    base = f"{marca} {modello}{allest_txt}{anno_txt}{colore_txt}"

    extra = f" Visual details: {precisazioni}." if precisazioni else ""

    return (
        f"Create a high-quality photo of a {base}. "
        "Factory-accurate proportions, design, color, branding. "
        "Luxury urban setting at dusk with realistic lighting and reflections. "
        "Three-quarter front view, crisp details, photographic realism. "
        f"{extra}"
        "No text, no watermarks, no non-Latin characters."
    )



async def _gemini_generate_image_sync(
    prompt: str,
    start_image_url: Optional[str] = None,
    start_image_bytes: Optional[bytes] = None,
    subject_image_url: Optional[str] = None,
    background_image_url: Optional[str] = None,
    num_images: int = 1,
    size: Optional[str] = None
) -> list[bytes]:
    """
    Genera una o più immagini con Gemini.
    Retry in memoria su errori transitori o risposte vuote.
    """
    _gemini_assert_api()
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image-preview:generateContent"

    # 🔹 Normalizza: accetta str o list e restituisce sempre str
    # normalizza input come stringa
    if start_image_url:
        start_image_url = _force_str(start_image_url)
    if subject_image_url:
        subject_image_url = _force_str(subject_image_url)
    if background_image_url:
        background_image_url = _force_str(background_image_url)


    MAX_RETRIES = 3
    images: list[bytes] = []

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            # ---- build parts ----
            parts = [{"text": prompt}]
            if start_image_bytes:
                parts.append({
                    "inline_data": {
                        "mime_type": "image/png",
                        "data": base64.b64encode(start_image_bytes).decode("utf-8")
                    }
                })
            elif start_image_url and start_image_url.strip():
                mime, b64 = await _fetch_image_base64_from_url(start_image_url.strip())
                parts.append({"inline_data": {"mime_type": mime, "data": b64}})

            for name, img_url in {
                "subject_image_url": subject_image_url,
                "background_image_url": background_image_url
            }.items():
                if img_url and img_url.strip():
                    mime, b64 = await _fetch_image_base64_from_url(img_url.strip())
                    parts.append({"inline_data": {"mime_type": mime, "data": b64}})

            payload = {
                "contents": [{"parts": parts}],
                "generationConfig": {"candidateCount": num_images},
            }
            if size:
                payload["generationConfig"]["size"] = size

            async with httpx.AsyncClient(timeout=120) as client:
                r = await client.post(
                    url, json=payload,
                    headers={
                        "x-goog-api-key": GEMINI_API_KEY,
                        "Content-Type": "application/json"
                    }
                )

            if r.status_code >= 300:
                if r.status_code == 400 and "safety" in r.text.lower():
                    raise HTTPException(400, f"Gemini policy violation: {r.text}")
                raise HTTPException(r.status_code, f"Errore Gemini image: {r.text}")

            data = r.json()

            # ---- extract images ----
            candidates = data.get("candidates", [])
            images = []
            for cand in candidates:
                parts = cand.get("content", {}).get("parts", [])
                for p in parts:
                    inline = (
                        p.get("inline_data")
                        or p.get("inlineData")
                        or p.get("inline")
                    )
                    if inline and inline.get("data"):
                        images.append(base64.b64decode(inline["data"]))

            if images:
                return images  # ✅ successo

            msg = (
                candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                if candidates else ""
            )
            if "immagine" in msg.lower() or "image" in msg.lower():
                logging.warning(f"[Gemini Retry] Tentativo {attempt}/{MAX_RETRIES}: solo testo")
                await asyncio.sleep(attempt * 2)
                continue

            raise HTTPException(502, f"Gemini image: nessuna immagine trovata. Resp: {data}")

        except HTTPException as e:
            if "policy" in str(e).lower() or "safety" in str(e).lower():
                logging.error(f"[Gemini STOP] Violazione policy: {e}")
                raise
            logging.warning(f"[Gemini Retry] Tentativo {attempt}/{MAX_RETRIES} fallito: {e}")
            await asyncio.sleep(attempt * 2)
            continue
        except Exception as e:
            logging.warning(f"[Gemini Retry] Tentativo {attempt}/{MAX_RETRIES} errore generico: {e}")
            await asyncio.sleep(attempt * 2)
            continue

    raise HTTPException(502, f"Gemini image fallita dopo {MAX_RETRIES} tentativi")




async def _nano_banana_generate_image(
    scenario: str,
    prompt: str,
    start_image_bytes: Optional[bytes] = None
) -> bytes:
    _gemini_assert_api()
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image-preview:generateContent"

    parts = [
        {"text": f"Scenario: {scenario}"},
        {"text": "Fotografia cinematografica ultra realistica, non rendering, non cartoon."},
        {"text": prompt}
    ]

    if start_image_bytes:
        parts.append({
            "inline_data": {
                "mime_type": "image/png",
                "data": base64.b64encode(start_image_bytes).decode("utf-8")
            }
        })

    payload = {"contents": [{"parts": parts}]}

    async with httpx.AsyncClient(timeout=180) as client:
        r = await client.post(url, json=payload, headers={
            "x-goog-api-key": GEMINI_API_KEY,
            "Content-Type": "application/json"
        })
        if r.status_code >= 300:
            raise HTTPException(r.status_code, f"Errore Nano Banana: {r.text}")

        data = r.json()

        parts = (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [])
        )
        for p in parts:
            inline = p.get("inline_data") or p.get("inlineData")
            if inline and inline.get("data"):
                return base64.b64decode(inline["data"])

        raise HTTPException(502, f"Nano Banana: nessuna immagine trovata. Resp: {data}")




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
    prompt = payload.prompt_override or _gemini_build_image_prompt(
        marca, modello, anno, colore, allestimento, auto.precisazioni
    )

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

     # 👇 se async_mode=True (es. Boost), torna subito senza generare
    if getattr(payload, "async_mode", False):
        return GeminiImageHeroResponse(
            success=True,
            id_auto=payload.id_auto,
            status="queued",
            public_url=None,
            error_message=None,
            usato_leonardo_id=rec.id,
            generation_id=None
        )
    
        # --- normalizzazione input (stessa logica auto-scenario) ---
    try:
        kwargs = {}
        if payload.start_image_url:
            s = _force_str(payload.start_image_url)
            if s:
                kwargs["start_image_url"] = s

        if payload.subject_image_url:
            s = _force_str(payload.subject_image_url)
            if s:
                kwargs["subject_image_url"] = s

        if payload.background_image_url:
            s = _force_str(payload.background_image_url)
            if s:
                kwargs["background_image_url"] = s


        img_bytes = await _gemini_generate_image_sync(prompt, **kwargs)


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


import mimetypes
from io import BytesIO

SUPABASE_BUCKET_SCENARI = os.getenv("SUPABASE_BUCKET_SCENARI", "scenari-dealer")

def _sb_upload_scenario(path: str, blob: bytes, content_type: str = "image/png") -> tuple[str, str | None]:
    # upload con bytes grezzi, come per _sb_upload_and_sign
    up = supabase_client.storage.from_(SUPABASE_BUCKET_SCENARI).upload(
        path=path,
        file=blob,
        file_options={"content-type": content_type, "upsert": "true"}
    )
    # log e hard-fail se l’SDK ritorna error
    if isinstance(up, dict) and up.get("error"):
        msg = up["error"].get("message", "unknown")
        logging.error(f"[SCENARIO-UPLOAD] error bucket={SUPABASE_BUCKET_SCENARI} path={path}: {msg}")
        raise HTTPException(502, f"Supabase upload error: {msg}")

    res = supabase_client.storage.from_(SUPABASE_BUCKET_SCENARI).create_signed_url(
        path=path, expires_in=60*60*24*30
    )
    url = res.get("signedURL") or res.get("signed_url") or res.get("signedUrl")

    # fallback public url
    if not url:
        pub = supabase_client.storage.from_(SUPABASE_BUCKET_SCENARI).get_public_url(path)
        url = pub.get("publicURL") or pub.get("publicUrl") or pub.get("public_url")

    if url and url.startswith("/storage"):
        base = os.getenv("SUPABASE_URL", "").rstrip("/")
        url = f"{base}{url}"

    logging.warning(f"[SCENARIO-UPLOAD] ok bucket={SUPABASE_BUCKET_SCENARI} path={path} url={url}")
    return path, url



class ScenarioDealerRequest(BaseModel):
    titolo: Optional[str] = None
    descrizione: str
    tags: Optional[str] = None
    image_url: Optional[str] = None  # 👈 nuovo campo

class ScenarioDealerUpdateRequest(BaseModel):
    titolo: Optional[str] = None
    descrizione: Optional[str] = None
    tags: Optional[str] = None
    image_url: Optional[str] = None  # 👈 nuovo campo


@router.post("/scenario-dealer/upload", tags=["Scenario Dealer"])
async def upload_scenario_image(
    file: UploadFile = File(...),
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()
    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(403, "Utente non trovato")

    ext = os.path.splitext(file.filename or "")[-1].lower() or ".png"
    path = f"{user.id}/{uuid4()}{ext}"
    blob = await file.read()
    ctype = file.content_type or "image/png"

    try:
        _, signed_url = _sb_upload_scenario(path, blob, ctype)
        return {"success": True, "url": signed_url}
    except Exception as e:
        logging.exception("Scenario upload failed")
        raise HTTPException(500, f"Upload fallito: {e}")



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

    records = db.query(ScenarioDealer)\
                .filter(ScenarioDealer.dealer_id == user.id)\
                .order_by(ScenarioDealer.created_at.desc())\
                .all()

    return [
        {
            "id": str(r.id),
            "titolo": r.titolo,
            "descrizione": r.descrizione,
            "tags": r.tags,
            "image_url": r.image_url,   # 👈 esponi url
            "created_at": r.created_at.isoformat(),
            "updated_at": r.updated_at.isoformat() if r.updated_at else None
        }
        for r in records
    ]


@router.post("/scenario-dealer", tags=["Scenario Dealer"])
async def crea_scenario_dealer(
    payload: ScenarioDealerRequest,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()
    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(403, "Utente non trovato")

    rec = ScenarioDealer(
        dealer_id=user.id,
        titolo=payload.titolo,
        descrizione=payload.descrizione,
        tags=payload.tags,
        image_url=payload.image_url   # 👈 salva url immagine
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
        "image_url": rec.image_url,
        "created_at": rec.created_at.isoformat()
    }


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

    rec = db.query(ScenarioDealer).filter(
        ScenarioDealer.id == id,
        ScenarioDealer.dealer_id == user.id
    ).first()
    if not rec:
        raise HTTPException(404, "Scenario non trovato")

    if payload.titolo is not None:
        rec.titolo = payload.titolo
    if payload.descrizione is not None:
        rec.descrizione = payload.descrizione
    if payload.tags is not None:
        rec.tags = payload.tags
    if payload.image_url is not None:
        rec.image_url = payload.image_url

    db.commit()
    db.refresh(rec)
    return {
        "success": True,
        "id": str(rec.id),
        "titolo": rec.titolo,
        "descrizione": rec.descrizione,
        "tags": rec.tags,
        "image_url": rec.image_url,
        "updated_at": rec.updated_at.isoformat() if rec.updated_at else None
    }



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



class WebpImageRequest(BaseModel):
    prompt: str
    start_image_url: Optional[str] = None          # compatibilità
    subject_image_url: Optional[str] = None        # nuovo opzionale
    background_image_url: Optional[str] = None     # nuovo opzionale



@router.post("/veo3/image-webp", tags=["Gemini VEO 3"])
async def genera_image_webp(payload: WebpImageRequest):
    try:
        _gemini_assert_api()
        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image-preview:generateContent"

        # Costruisci parts
        parts = [{"text": payload.prompt}]

        for name, img_url in {
            "start_image_url": payload.start_image_url,
            "subject_image_url": payload.subject_image_url,
            "background_image_url": payload.background_image_url
        }.items():
            if img_url:
                mime, b64 = await _fetch_image_base64_from_url(img_url)
                parts.append({
                    "inline_data": {
                        "mime_type": mime,
                        "data": b64
                    }
                })

        request_payload = {"contents": [{"parts": parts}]}

        # Chiamata a Gemini con Authorization Bearer
        async with httpx.AsyncClient(timeout=180) as client:
            r = await client.post(
                url,
                json=request_payload,
                 headers = {
                    "x-goog-api-key": GEMINI_API_KEY,
                    "Content-Type": "application/json"
                }

            )
            if r.status_code >= 300:
                raise HTTPException(r.status_code, f"Errore Gemini image: {r.text}")

            data = r.json()
            result_parts = (
                data.get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [])
            )
            img_bytes = None
            for p in result_parts:
                inline = (
                    p.get("inline_data")
                    or p.get("inlineData")
                    or p.get("inline")
                )
                if inline and inline.get("data"):
                    img_bytes = base64.b64decode(inline["data"])
                    break

            if not img_bytes:
                raise HTTPException(502, f"Gemini image: nessuna immagine trovata. Resp: {data}")

        # Converti in .webp in memoria
        img = Image.open(io.BytesIO(img_bytes))
        buf = io.BytesIO()
        img.save(buf, format="WEBP", quality=90)
        buf.seek(0)

        return Response(
            content=buf.read(),
            media_type="image/webp",
            headers={"Content-Disposition": 'attachment; filename="output.webp"'}
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore generazione immagine: {e}")


# --- DALLE COMBINE (JWT + credito + upload + storico) -----------------------

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    organization=os.getenv("OPENAI_ORG_ID")
)

DALLE_CREDIT_COST = float(os.getenv("DALLE_CREDIT_COST", "1.5"))

QUALITY_MAP = {"standard": "medium", "hd": "high"}
ALLOWED_QUALITY = {"low", "medium", "high", "auto"}
ORIENTATION_SIZE = {
    "square": "1024x1024",
    "landscape": "1792x1024",
    "portrait": "1024x1792"
}

class DalleCombineRequest(BaseModel):
    id_auto: _UUID
    prompt: str
    img1_url: str
    img2_url: str
    quality: str = "medium"
    orientation: str = "square"
    logo_url: str | None = None
    logo_height: int = 100
    logo_offset_y: int = 100
    

class DalleCombineResponse(BaseModel):
    success: bool
    id_auto: _UUID
    public_url: str
    usato_leonardo_id: _UUID
    status: str = "completed"

def _load_image_from_url(url: str, field: str) -> Image.Image:
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        return Image.open(BytesIO(r.content)).convert("RGB")
    except Exception:
        raise HTTPException(400, f"Invalid image URL for '{field}'")


# --- DALLE COMBINE (enqueue asincrono: JWT + credito + storico) ------------
import os
import logging
from uuid import UUID as _UUID
from pydantic import BaseModel
from fastapi import Depends, HTTPException
from fastapi_jwt_auth import AuthJWT
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, UsatoLeonardo, CreditTransaction
from app.utils.notifications import inserisci_notifica
# usa la tua funzione esistente
# from app.utils.roles import is_dealer_user  # se serve, altrimenti lascialo com'è nel tuo file

DALLE_CREDIT_COST = float(os.getenv("DALLE_CREDIT_COST", "1.5"))
GEMINI_MODEL_ID = os.getenv("GEMINI_MODEL_ID", "gemini-2.5-flash-image-preview")

ALLOWED_QUALITY = {"low", "medium", "high", "auto"}  # solo validazione, non usata da Gemini
ORIENTATION_SIZE = {
    "square": "1024x1024",
    "landscape": "1792x1024",
    "portrait": "1024x1792"
}

class DalleCombineRequest(BaseModel):
    id_auto: _UUID
    prompt: str
    img1_url: str | None = None     # opzionale
    img2_url: str | None = None     # opzionale
    quality: str = "medium"
    orientation: str = "square"
    logo_url: str | None = None
    logo_height: int = 100
    logo_offset_y: int = 100
    num_images: int = 1             # nuovo parametro (1–4)

class DalleCombineResponse(BaseModel):
    success: bool
    id_auto: _UUID
    public_urls: list[str | None]   # lista, verrà popolata dal cron
    usato_leonardo_ids: list[_UUID] # lista di record creati
    status: str                     # queued | completed | failed


def _validate_payload(p: DalleCombineRequest):
    if not p.prompt or not p.prompt.strip():
        raise HTTPException(400, "prompt is required")

    if not (1 <= p.num_images <= 4):
        raise HTTPException(400, "num_images must be between 1 and 4")

    if p.orientation not in ORIENTATION_SIZE:
        raise HTTPException(400, f"orientation must be one of: {', '.join(ORIENTATION_SIZE)}")

    if p.quality.lower() not in ALLOWED_QUALITY:
        raise HTTPException(400, f"quality must be one of: {', '.join(ALLOWED_QUALITY)}")


@router.post("/ai/dalle/combine", response_model=DalleCombineResponse, tags=["OpenAI"])
async def dalle_combine(
    payload: DalleCombineRequest,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    # --- Auth ---
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()
    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(403, "Utente non trovato")

    is_dealer = is_dealer_user(user)
    total_cost = DALLE_CREDIT_COST * payload.num_images

    if is_dealer and (user.credit is None or user.credit < total_cost):
        raise HTTPException(402, "Credito insufficiente")

    # --- Validazioni ---
    _validate_payload(payload)

    created_ids = []
    try:
        for i in range(payload.num_images):
            rec = UsatoLeonardo(
                id_auto=payload.id_auto,
                provider="gemini",
                generation_id=None,
                status="queued",
                media_type="image",
                mime_type="image/png",
                prompt=payload.prompt,
                negative_prompt=None,
                model_id=GEMINI_MODEL_ID,
                aspect_ratio=payload.orientation,
                credit_cost=DALLE_CREDIT_COST if is_dealer else 0.0,
                user_id=user.id,
                subject_url=payload.img1_url,
                background_url=payload.img2_url,
                logo_url=payload.logo_url,
                logo_height=payload.logo_height,
                logo_offset_y=payload.logo_offset_y,
                retry_count=0
            )
            db.add(rec)
            db.commit()
            db.refresh(rec)
            created_ids.append(rec.id)

    except Exception as e:
        db.rollback()
        logging.error("Errore creazione record UsatoLeonardo: %s", e)
        raise HTTPException(500, "Errore creazione job immagine")

    # --- Addebito credito immediato (solo dealer) ---
    if is_dealer:
        try:
            user.credit = float(user.credit or 0) - total_cost
            db.add(CreditTransaction(
                dealer_id=user.id,
                amount=-total_cost,
                transaction_type="USE",
                note=f"Immagini Gemini combine (enqueue) x{payload.num_images}"
            ))
            inserisci_notifica(
                db=db,
                utente_id=user.id,
                tipo_codice="CREDITO_USATO",
                messaggio=f"Hai utilizzato {total_cost:g} crediti per la generazione di {payload.num_images} immagine/i Gemini."
            )
            db.commit()
        except Exception as e:
            db.rollback()
            logging.error("Errore addebito credito per user_id=%s rec_ids=%s: %s", user.id, created_ids, e)

    # --- Risposta immediata ---
    return DalleCombineResponse(
        success=True,
        id_auto=payload.id_auto,
        public_urls=[None] * payload.num_images,
        usato_leonardo_ids=created_ids,
        status="queued"
    )



@router.post("old/ai/dalle/combine", response_model=DalleCombineResponse, tags=["OpenAI"])
async def dalle_combine(
    payload: DalleCombineRequest,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    # --- JWT + user ---
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()
    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(403, "Utente non trovato")

    is_dealer = is_dealer_user(user)
    if is_dealer and (user.credit is None or user.credit < DALLE_CREDIT_COST):
        raise HTTPException(402, "Credito insufficiente")

    # --- validazioni qualità/orientamento ---
    q = QUALITY_MAP.get(payload.quality.lower(), payload.quality.lower())
    if q not in ALLOWED_QUALITY:
        raise HTTPException(400, "quality must be one of: low, medium, high, auto (or standard/hd)")
    if payload.orientation not in ORIENTATION_SIZE:
        raise HTTPException(400, "orientation must be one of: square, landscape, portrait")
    size = ORIENTATION_SIZE[payload.orientation]

    # --- carica immagini e composizione ---
    i1 = _load_image_from_url(payload.img1_url, "img1_url")
    i2 = _load_image_from_url(payload.img2_url, "img2_url")
    w, h = i1.width + i2.width, max(i1.height, i2.height)
    canvas = Image.new("RGB", (w, h), (255, 255, 255))
    canvas.paste(i1, (0, 0))
    canvas.paste(i2, (i1.width, 0))

    buf = BytesIO()
    canvas.save(buf, format="PNG")
    buf.seek(0)
    buf.name = "canvas.png"

    # --- crea record storico (queued) ---
    rec = UsatoLeonardo(
        id_auto=payload.id_auto,
        provider="dalle",
        generation_id=None,
        status="queued",
        media_type="image",
        mime_type="image/png",
        prompt=payload.prompt,
        negative_prompt=None,
        model_id="gpt-image-1",
        aspect_ratio=payload.orientation,
        credit_cost=DALLE_CREDIT_COST if is_dealer else 0.0,
        user_id=user.id
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)

    # --- chiamata DALL·E ---
    try:
        dalle_res = client.images.edit(
            model="gpt-image-1",
            prompt=payload.prompt,
            image=buf,
            size=size,
            quality=q,
        )
    except Exception as e:
        rec.status = "failed"
        rec.error_message = f"DALL·E error: {str(e)}"
        db.commit()
        raise HTTPException(500, rec.error_message)

    # --- decodifica immagine ---
    try:
        img_b64 = dalle_res.data[0].b64_json
        img_bytes = base64.b64decode(img_b64)
        final = Image.open(BytesIO(img_bytes)).convert("RGBA")
    except Exception as e:
        rec.status = "failed"
        rec.error_message = f"Image decode error: {str(e)}"
        db.commit()
        raise HTTPException(500, rec.error_message)

    # --- applica logo opzionale ---
    if payload.logo_url:
        try:
            r = requests.get(payload.logo_url, timeout=30)
            r.raise_for_status()
            logo = Image.open(BytesIO(r.content)).convert("RGBA")
            ow, oh = logo.size
            new_h = max(1, int(payload.logo_height))
            new_w = int((ow / oh) * new_h)
            logo = logo.resize((new_w, new_h))
            if final.height < new_h + payload.logo_offset_y:
                raise HTTPException(400, f"image too small for logo offset {payload.logo_offset_y}px")
            logo_x = (final.width - new_w) // 2
            logo_y = payload.logo_offset_y
            final.paste(logo, (logo_x, logo_y), logo)
        except HTTPException:
            raise
        except Exception as e:
            rec.status = "failed"
            rec.error_message = f"logo_url error: {str(e)}"
            db.commit()
            raise HTTPException(400, rec.error_message)

    # --- serializza PNG ---
    output_png = BytesIO()
    final.save(output_png, format="PNG")
    output_png.seek(0)

    # --- upload su Supabase + finalize ---
    try:
        path = f"{str(rec.id_auto)}/{str(rec.id)}.png"
        _, signed_url = _sb_upload_and_sign(path, output_png.getvalue(), "image/png")
        rec.public_url = signed_url
        rec.storage_path = path
        rec.status = "completed"
        db.commit()
    except Exception as e:
        db.rollback()
        rec.status = "failed"
        rec.error_message = f"Upload error: {str(e)}"
        db.commit()
        raise HTTPException(500, rec.error_message)

    # --- addebito credito dealer ---
    if is_dealer:
        try:
            user.credit = float(user.credit or 0) - DALLE_CREDIT_COST
            db.add(CreditTransaction(
                dealer_id=user.id,
                amount=-DALLE_CREDIT_COST,
                transaction_type="USE",
                note="Immagine DALL·E combine"
            ))
            inserisci_notifica(
                db=db,
                utente_id=user.id,
                tipo_codice="CREDITO_USATO",
                messaggio=f"Hai utilizzato {DALLE_CREDIT_COST:g} crediti per la generazione immagine DALL·E."
            )
            db.commit()
        except Exception:
            db.rollback()
            logging.error("Errore addebito credito DALL·E per user_id=%s rec_id=%s", user.id, rec.id)

    # --- risposta ---
    return DalleCombineResponse(
        success=True,
        id_auto=payload.id_auto,
        public_url=rec.public_url,
        usato_leonardo_id=rec.id,
        status="completed"
    )


# --- GEMINI AUTO + SCENARIO (2-step con credito + upload + storico + LOG) ---
import os, time, logging, urllib.parse
from typing import Union, List
from uuid import UUID
from fastapi import Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

IMG_COST = float(os.getenv("GEMINI_IMG_CREDIT_COST", "1.5"))
_logger = logging.getLogger("gemini.auto_scenario")

def _mask_url(u: str) -> str:
    try:
        p = urllib.parse.urlparse(u)
        return f"{p.scheme}://{p.netloc}{p.path}" + ("?…" if p.query else "")
    except Exception:
        return str(u)[:200]

def _force_str(val) -> str:
    if not val:
        return ""
    if isinstance(val, str):
        return val.strip()
    if isinstance(val, (list, tuple)):
        for v in val:
            s = _force_str(v)
            if s:
                return s
    raise HTTPException(400, f"Valore non valido per URL immagine: {val!r}")

from rembg import remove
from PIL import Image

def remove_bg(img_bytes: bytes) -> Image.Image:
    result = remove(img_bytes)
    return Image.open(io.BytesIO(result)).convert("RGBA")

def _download_image(url: str) -> Image.Image:
    resp = requests.get(url, timeout=20)
    resp.raise_for_status()
    return Image.open(io.BytesIO(resp.content)).convert("RGBA")

def _trim_alpha(im: Image.Image) -> Image.Image:
    if im.mode != "RGBA":
        im = im.convert("RGBA")
    bbox = im.getchannel("A").getbbox()
    return im.crop(bbox) if bbox else im

def _compose_with_pedana_images(car: Image.Image, bg: Image.Image,
                                scale_rel: float = 2.2,
                                y_offset_rel: float = 0.12) -> bytes:
    # rimuovi padding trasparente
    car = _trim_alpha(car)
    orig_size = car.size

    pedana_diam = int(bg.width * 0.6)
    new_w = max(1, int(pedana_diam * scale_rel))
    ratio = new_w / car.width
    new_h = max(1, int(car.height * ratio))
    car = car.resize((new_w, new_h), Image.LANCZOS)

    x = (bg.width - car.width) // 2
    y = (bg.height - car.height) // 2 + int(bg.height * y_offset_rel)

    _logger.info("PEDANA diam=%d scale=%.2f car_before=%s car_after=%s pos=(%d,%d)",
                 pedana_diam, scale_rel, orig_size, car.size, x, y)

    composed = bg.copy()
    composed.alpha_composite(car, (x, y))
    buf = io.BytesIO(); composed.save(buf, "PNG")
    return buf.getvalue()




def ensure_transparency(img_bytes: bytes) -> bytes:
    """
    Verifica se l'immagine ha canale alpha reale.
    Se non lo ha, usa rembg per rimuovere lo sfondo.
    Restituisce sempre bytes PNG RGBA.
    """
    im = Image.open(io.BytesIO(img_bytes))
    if im.mode == "RGBA":
        mn, mx = im.getchannel("A").getextrema()
        if mn < 255:
            # ha già trasparenza
            return img_bytes
    # forza trasparenza con rembg
    result = remove(img_bytes)
    return result



class GeminiAutoScenarioRequest(BaseModel):
    id_auto: UUID
    img1_url: Union[str, List[str]]
    img2_url: Union[str, List[str]] | None = None
    scenario_prompt: str | None = None
    num_variants: int = 1

@router.post("/ai/gemini/auto-scenario")
async def gemini_auto_scenario(
    payload: GeminiAutoScenarioRequest,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    t0 = time.perf_counter()
    Authorize.jwt_required()
    user_email = Authorize.get_jwt_subject()

    # Normalizza input
    img1 = _force_str(payload.img1_url)
    img2 = _force_str(payload.img2_url) if payload.img2_url else None
    scenario_prompt = (payload.scenario_prompt or "").strip() if payload.scenario_prompt else None

    if not img1:
        raise HTTPException(400, "img1_url obbligatorio")
    if not (img2 or scenario_prompt):
        raise HTTPException(400, "Devi passare img2_url oppure scenario_prompt")

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise HTTPException(403, "Utente non trovato")

    is_dealer = is_dealer_user(user)
    if is_dealer and (user.credit is None or user.credit < IMG_COST):
        raise HTTPException(402, "Credito insufficiente")

    _logger.info(
        "AUTO-SCENARIO start user=%s id_auto=%s img1=%s img2=%s prompt=%s",
        user_email, str(payload.id_auto), _mask_url(img1),
        _mask_url(img2) if img2 else None,
        (scenario_prompt[:80] + "...") if scenario_prompt else None
    )

    _gemini_assert_api()

    # --- STEP A: pulizia auto ---
    prompt_clean = (
        "Nell’immagine allegata rimuovi completamente lo sfondo e sistema luce e riflessi presenti sul soggetto."
    )

    rec_clean = UsatoLeonardo(
        id_auto=payload.id_auto,
        provider="gemini",
        status="queued",
        media_type="image",
        mime_type="image/png",
        prompt=prompt_clean,
        model_id="gemini-2.5-flash-image-preview",
        aspect_ratio="16:9",
        credit_cost=0.0,
        user_id=user.id,
        subject_url=img1,
        is_deleted=True
    )
    db.add(rec_clean); db.commit(); db.refresh(rec_clean)
    _logger.info("STEP A queued rec_clean_id=%s", str(rec_clean.id))

    try:
        img_bytes_list = await _gemini_generate_image_sync(
            prompt_clean,
            start_image_url=img1
        )
        if not img_bytes_list:
            raise HTTPException(502, "Gemini non ha restituito immagini allo step A")

        img_bytes = img_bytes_list[0]
        img_bytes = ensure_transparency(img_bytes)

        pathA = f"{str(rec_clean.id_auto)}/{str(rec_clean.id)}.png"
        _, signed_urlA = _sb_upload_and_sign(pathA, img_bytes, "image/png")

        rec_clean.public_url = signed_urlA
        rec_clean.storage_path = pathA
        rec_clean.status = "completed"
        db.commit()
        _logger.info("STEP A uploaded path=%s url=%s", pathA, _mask_url(signed_urlA))

    except Exception as e:
        rec_clean.status = "failed"; rec_clean.error_message = str(e)
        db.commit()
        _logger.exception("STEP A Exception")
        raise HTTPException(500, f"Errore generazione step A (pulizia): {e}")

        # --- STEP B: composizione auto + scenario ---
    if img2:
        prompt_compose = (
            "Crea un’immagine professionale fotorealistica. Prendi l’auto dalla foto allegata e posizionala senza "
            "soluzione di continuità esattamente al centro della pedana nello scenario nell’altra immagine allegata. "
            "L’auto deve poggiare saldamente sul piano del terreno della scena, con tutte e quattro le ruote che toccano naturalmente. "
            "Mantieni invariati l’inquadratura originale, l’angolo di ripresa e la prospettiva della foto dell’auto fornita. "
            "L’auto deve apparire perfettamente integrata, centrata e scalata in modo naturale ed essere il soggetto in primo piano della scena. "
            "Il risultato deve essere indistinguibile da una vera fotografia ad alta risoluzione. "
            "Usa un look da obiettivo 200mm e una ripresa molto ravvicinata all’auto."
        )
    else:
        prompt_compose = scenario_prompt

    variants = []
    last_rec_final = None
    num = max(1, payload.num_variants or 1)

    for _ in range(num):
        rec_final = UsatoLeonardo(
            id_auto=payload.id_auto,
            provider="gemini" if not img2 else "pillow",
            status="queued",
            media_type="image",
            mime_type="image/png",
            prompt=prompt_compose,
            model_id="gemini-2.5-flash-image-preview" if not img2 else "pillow-compose",
            aspect_ratio="16:9",
            credit_cost=IMG_COST if is_dealer else 0.0,
            user_id=user.id,
            subject_url=rec_clean.public_url,
            background_url=img2 if img2 else None,
            is_deleted=False
        )
        db.add(rec_final); db.commit(); db.refresh(rec_final)

        try:
            if img2:
                # --- composizione con Pillow direttamente dai bytes Step A ---
                bg_img  = _download_image(img2)
                car_img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")  # img_bytes = output Step A
                img_bytesB = _compose_with_pedana_images(car_img, bg_img, scale_rel=1.0, y_offset_rel=0.12)

            else:
                # --- generazione AI classica ---
                img_bytesB_list = await _gemini_generate_image_sync(
                    prompt_compose,
                    subject_image_url=_force_str(rec_clean.public_url)
                )
                if not img_bytesB_list:
                    raise HTTPException(502, "Gemini non ha restituito immagini allo step B")
                img_bytesB = img_bytesB_list[0]

            # upload
            pathB = f"{str(rec_final.id_auto)}/{str(rec_final.id)}.png"
            _, signed_urlB = _sb_upload_and_sign(pathB, img_bytesB, "image/png")

            rec_final.public_url = signed_urlB
            rec_final.storage_path = pathB
            rec_final.status = "completed"
            db.commit()
            variants.append({"id": str(rec_final.id), "public_url": signed_urlB})
            last_rec_final = rec_final
            _logger.info("STEP B uploaded path=%s url=%s", pathB, _mask_url(signed_urlB))

        except Exception as e:
            rec_final.status = "failed"; rec_final.error_message = str(e)
            db.commit()
            _logger.exception("STEP B Exception")


    if not last_rec_final:
        raise HTTPException(502, "Tutte le varianti step B sono fallite")

    # --- credito dealer ---
    if is_dealer:
        try:
            pre_credit = float(user.credit or 0)
            user.credit = pre_credit - IMG_COST
            db.add(CreditTransaction(
                dealer_id=user.id,
                amount=-IMG_COST,
                transaction_type="USE",
                note="Gemini auto+scenario"
            ))
            inserisci_notifica(
                db=db,
                utente_id=user.id,
                tipo_codice="CREDITO_USATO",
                messaggio=f"Hai utilizzato {IMG_COST:g} crediti per la generazione immagine AI (auto+scenario)."
            )
            db.commit()
            _logger.info("CREDIT debited dealer_id=%s from=%.3f to=%.3f",
                         user.id, pre_credit, float(user.credit or 0))
        except Exception:
            db.rollback()
            _logger.exception("CREDIT debit failed (non bloccante)")

    _logger.info(
        "AUTO-SCENARIO done id_auto=%s final_id=%s total_time=%.2fs",
        str(payload.id_auto), str(last_rec_final.id), time.perf_counter() - t0
    )

    return {
        "success": True,
        "id_auto": str(payload.id_auto),
        "status": last_rec_final.status,
        "public_url": last_rec_final.public_url,
        "usato_leonardo_id": str(last_rec_final.id),
        "variants": variants
    }
