from fastapi import APIRouter, Depends, HTTPException
from fastapi_jwt_auth import AuthJWT
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session
from datetime import datetime
import uuid, io, os, logging
from PIL import Image

from app.database import get_db, supabase_client
from app.models import MnetModelli
from app.routes.openai_config import _gemini_generate_image_sync  # async

router = APIRouter(tags=["Modelli AI - Test"])

SUPABASE_BUCKET_MODELLI_AI = os.getenv("SUPABASE_BUCKET_MODELLI_AI", "modelli-ai")
WEBP_QUALITY = int(os.getenv("MODEL_AI_WEBP_QUALITY", "90"))

SQL_PICK_START = """
WITH foto_rank AS (
  SELECT
    a.codice_modello,
    i.url,
    ROW_NUMBER() OVER (
      PARTITION BY a.codice_modello
      ORDER BY CASE
        WHEN i.codice_visuale='0001' THEN 1
        WHEN i.codice_visuale='0007' THEN 2
        WHEN i.codice_visuale='0009' THEN 3
        ELSE 4 END, i.url
    ) AS rn
  FROM public.mnet_allestimenti a
  JOIN public.mnet_immagini i ON i.codice_motornet_uni = a.codice_motornet_uni
  WHERE i.url IS NOT NULL
)
SELECT m.codice_modello, m.descrizione AS modello, m.marca_acronimo AS brand, f.url AS start_url
FROM public.mnet_modelli m
JOIN foto_rank f ON f.codice_modello = m.codice_modello AND f.rn = 1
WHERE m.codice_modello = :codice_modello
LIMIT 1;
"""

class ModelloAITestRequest(BaseModel):
    codice_modello: str | None = None
    start_image_url: str | None = None
    prompt: str | None = None
    save: bool = False  # se True aggiorna DB e conserva su bucket

class ModelloAITestResponse(BaseModel):
    codice_modello: str
    brand: str | None
    modello: str | None
    used_start_url: str
    used_prompt: str
    public_url: str | None
    storage_path: str | None
    saved: bool

def _sb_upload_and_sign_bucket(path: str, blob: bytes, content_type: str) -> tuple[str, str | None]:
    supabase_client.storage.from_(SUPABASE_BUCKET_MODELLI_AI).upload(
        path=path,
        file=blob,
        file_options={"content-type": content_type, "upsert": "true"}
    )
    res = supabase_client.storage.from_(SUPABASE_BUCKET_MODELLI_AI).create_signed_url(
        path=path, expires_in=60 * 60 * 24 * 365
    )
    signed = res.get("signedURL") or res.get("signed_url") or res.get("signedUrl")
    base = os.getenv("SUPABASE_URL", "").rstrip("/")
    if signed and signed.startswith("/storage") and base:
        signed = f"{base}{signed}"
    return path, signed

def _to_webp(png_bytes: bytes) -> bytes:
    img = Image.open(io.BytesIO(png_bytes))
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=WEBP_QUALITY)
    return buf.getvalue()

def _build_prompt(brand: str | None, model: str | None) -> str:
    b = brand or ""
    m = model or ""
    return (
        f"Migliora questa foto ufficiale del modello {b} {m}. "
        "Mantieni proporzioni, design, colori e loghi di fabbrica fedeli. "
        "Illuminazione cinematografica al tramonto, riflessi realistici, rimozione artefatti. "
        "Nessun testo sovrapposto o watermark. Conserva l'angolo di scatto originale."
    )

@router.post("/modelli-ai/test", response_model=ModelloAITestResponse)
async def modelli_ai_test(
    payload: ModelloAITestRequest,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()

    # 1) Risolvi start_image_url e metadati modello
    brand = modello = None
    start_url = payload.start_image_url
    codice_modello = payload.codice_modello

    if not start_url:
        if not codice_modello:
            raise HTTPException(422, "Serve 'codice_modello' oppure 'start_image_url'.")
        row = db.execute(text(SQL_PICK_START), {"codice_modello": codice_modello}).mappings().first()
        if not row:
            raise HTTPException(404, f"Nessuna foto trovata per codice_modello={codice_modello}")
        start_url = row["start_url"]
        brand = row["brand"]
        modello = row["modello"]
    else:
        if not codice_modello:
            # prova a ricavarlo dal DB se esiste una riga con ai_foto_url o descrizione
            codice_modello = "MANUALE"

    # 2) Prompt
    used_prompt = payload.prompt or _build_prompt(brand, modello)

    # 3) Gemini generate (image edit)
    def download_with_retry(url: str, retries: int = 4, delay: float = 2.0) -> bytes:
        import requests
        for attempt in range(1, retries + 1):
            try:
                r = requests.get(url, timeout=10)
                r.raise_for_status()
                return r.content
            except Exception as e:
                wait = delay * attempt
                logging.warning(f"❌ Download fallito ({e}) da {url} → retry {attempt}/{retries} in {wait:.1f}s")
                time.sleep(wait)
        raise Exception(f"💥 Impossibile scaricare immagine dopo {retries} tentativi: {url}")

    # 3) Scarica immagine con retry → poi Gemini
    try:
        img_bytes = download_with_retry(start_url)
        png_bytes = await _gemini_generate_image_sync(prompt=used_prompt, start_image_bytes=img_bytes)
    except Exception as e:
        raise HTTPException(502, f"Errore Gemini: {e}")


    # 4) WEBP + upload
    webp_bytes = _to_webp(png_bytes)
    fname = f"{codice_modello}/{uuid.uuid4()}.webp"
    storage_path, public_url = _sb_upload_and_sign_bucket(fname, webp_bytes, "image/webp")

    saved = False
    # 5) Aggiorna DB se richiesto e se codice_modello è reale
    if payload.save and codice_modello != "MANUALE":
        rec = db.query(MnetModelli).filter(MnetModelli.codice_modello == codice_modello).first()
        if not rec:
            raise HTTPException(404, f"Modello {codice_modello} non trovato per il salvataggio.")
        rec.ai_foto_url = public_url
        rec.ai_foto_prompt = used_prompt
        rec.ai_foto_updated_at = datetime.utcnow()
        db.commit()
        saved = True

    return ModelloAITestResponse(
        codice_modello=codice_modello,
        brand=brand,
        modello=modello,
        used_start_url=start_url,
        used_prompt=used_prompt,
        public_url=public_url,
        storage_path=storage_path,
        saved=saved
    )
