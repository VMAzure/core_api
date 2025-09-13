from fastapi import APIRouter, Depends, HTTPException
from fastapi_jwt_auth import AuthJWT
from sqlalchemy import text
from sqlalchemy.orm import Session
from datetime import datetime
import uuid, io, os, logging, time, base64
from PIL import Image
import httpx

from pydantic import BaseModel
from app.database import get_db, supabase_client
from app.models import MnetModelli, MnetModelliAIFoto

router = APIRouter(tags=["Modelli AI - Test"])

SUPABASE_BUCKET_MODELLI_AI = os.getenv("SUPABASE_BUCKET_MODELLI_AI", "modelli-ai")
WEBP_QUALITY = int(os.getenv("MODEL_AI_WEBP_QUALITY", "90"))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or ""

# ----------- PROMPTS OTTIMIZZATI ------------
SCENARIO_PROMPTS = {
    "indoor": "Fotografia cinematografica realistica in showroom auto premium, "
              "pavimento lucido riflettente, grandi vetrate con zona commerciale viva a giorno fuori. "
              "Scatto con lente 85mm, HDR, prospettiva naturale. "
              "Auto in primo piano al 75% della larghezza. "
              "Targa bianca con scritta AZURE, carattere Sans bold uppercase. "
              "No rendering, no cartoon, no watermark.",

    "mediterraneo": "Fotografia cinematografica realistica ambientata in un borgo mediterraneo sul mare, "
                    "trattoria tipica con tovaglie a quadretti, lucine calde, persone in aperitivo. "
                    "Vista sul porto con barche. Tramonto dorato. "
                    "Scatto 85mm, profondità di campo realistica. "
                    "Auto in primo piano al 75% della larghezza. "
                    "Targa bianca con scritta AZURE, carattere Sans bold uppercase. "
                    "No rendering, no cartoon, no watermark.",

    "cortina": "Fotografia cinematografica realistica in località alpina modaiola, "
               "negozi e hotel di montagna sullo sfondo, tanta neve che amplifica la luce. "
               "Scatto 85mm, atmosfera serale. "
               "Auto in primo piano al 75% della larghezza. "
               "Targa bianca con scritta AZURE, carattere Sans bold uppercase. "
               "No rendering, no cartoon, no watermark.",

    "milano": "Fotografia cinematografica realistica in città metropolitana elegante, "
              "ristoranti e movida serale sullo sfondo, alberi illuminati. "
              "Scatto 85mm, luce cinematografica al tramonto, riflessi realistici. "
              "Auto in primo piano al 75% della larghezza. "
              "Targa bianca con scritta AZURE, carattere Sans bold uppercase. "
              "No rendering, no cartoon, no watermark."
}

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

# ------------ RESPONSE MODELS ----------------
class ScenarioImage(BaseModel):
    scenario: str
    url: str

class ModelloAITestResponse(BaseModel):
    codice_modello: str
    results: list[ScenarioImage]

# ------------ UTILS ----------------
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
    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=WEBP_QUALITY)
    return buf.getvalue()

def download_with_retry(url: str, retries: int = 5, base_delay: float = 2.0, min_size: int = 50_000) -> bytes:
    import requests
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            logging.info(f"⬇️ Tentativo {attempt}/{retries} download immagine da {url}")
            r = requests.get(url, timeout=30, stream=True)
            r.raise_for_status()
            content = r.content
            if len(content) < min_size:
                raise ValueError(f"Contenuto troppo piccolo ({len(content)} bytes)")
            return content
        except Exception as e:
            last_err = e
            wait = base_delay * (2 ** (attempt - 1))
            logging.warning(f"❌ Download fallito ({e}) → retry in {wait:.1f}s")
            time.sleep(wait)
    raise HTTPException(424, f"Impossibile scaricare immagine. Ultimo errore: {last_err}")

# ------------ NUOVA FUNZIONE NANO BANANA -------------
async def _nano_banana_generate_image(scenario: str, prompt: str, start_image_bytes: bytes) -> bytes:
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image-preview:generateContent"

    parts = [
        {"text": f"Scenario: {scenario}"},
        {"text": "Fotografia cinematografica ultra realistica, non rendering, non cartoon."},
        {"text": prompt},
        {
            "inline_data": {
                "mime_type": "image/png",
                "data": base64.b64encode(start_image_bytes).decode("utf-8")
            }
        }
    ]

    payload = {"contents": [{"parts": parts}]}
    logging.info(f"🌐 Chiamo Gemini per {scenario}")
    async with httpx.AsyncClient(timeout=180) as client:
        r = await client.post(url, json=payload, headers={
            "x-goog-api-key": GEMINI_API_KEY,
            "Content-Type": "application/json"
        })
    logging.info(f"🌐 Risposta Gemini {scenario}: {r.status_code}")

    async with httpx.AsyncClient(timeout=180) as client:
        r = await client.post(url, json=payload, headers={
            "x-goog-api-key": GEMINI_API_KEY,
            "Content-Type": "application/json"
        })
        if r.status_code >= 300:
            raise HTTPException(r.status_code, f"Errore Nano Banana: {r.text}")

        data = r.json()
        logging.warning(f"📦 Risposta grezza Gemini: {data}")

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

# ------------ ROUTE -------------
@router.post("/modelli-ai/test/{codice_modello}", response_model=ModelloAITestResponse)
async def modelli_ai_test(
    codice_modello: str,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()

    # 1) Start image dal DB
    row = db.execute(text(SQL_PICK_START), {"codice_modello": codice_modello}).mappings().first()
    if not row:
        raise HTTPException(404, f"Nessuna foto trovata per codice_modello={codice_modello}")

    start_url = row["start_url"]
    img_bytes = download_with_retry(start_url)

    results = []
    for scenario, prompt in SCENARIO_PROMPTS.items():
        # controlla se già esiste
        foto = (
            db.query(MnetModelliAIFoto)
            .filter(
                MnetModelliAIFoto.codice_modello == codice_modello,
                MnetModelliAIFoto.scenario == scenario
            )
            .first()
        )

        if foto and foto.ai_foto_url:   # già generata
            logging.info(f"⏩ Skip {codice_modello} - {scenario}, già presente")
            continue

        logging.info(f"▶️ Genero {codice_modello} - {scenario}")

        try:
            png_bytes = await _nano_banana_generate_image(scenario, prompt, img_bytes)
            webp_bytes = _to_webp(png_bytes)
            fname = f"{codice_modello}/{scenario}-{uuid.uuid4()}.webp"
            storage_path, public_url = _sb_upload_and_sign_bucket(fname, webp_bytes, "image/webp")

            if not foto:
                foto = MnetModelliAIFoto(codice_modello=codice_modello, scenario=scenario)
                db.add(foto)

            foto.ai_foto_url = public_url
            foto.ai_foto_prompt = prompt
            foto.ai_foto_updated_at = datetime.utcnow()
            db.commit()

            logging.info(f"✅ Salvata {codice_modello} - {scenario}")
        except Exception as e:
            logging.error(f"❌ Errore {codice_modello} - {scenario}: {e}")


    return ModelloAITestResponse(
        codice_modello=codice_modello,
        results=results
    )

@router.post("/modelli-ai/sync-mnet")
async def sync_immagini_mnet(db: Session = Depends(get_db)):
    rows = db.execute(text("SELECT codice_modello FROM public.mnet_modelli")).mappings().all()
    logging.info(f"🔄 Avvio sync immagini AI per {len(rows)} modelli")

    report = []

    for row in rows:
        codice_modello = row["codice_modello"]
        modello_report = {"codice_modello": codice_modello, "scenari": {}}

        try:
            pick = db.execute(text(SQL_PICK_START), {"codice_modello": codice_modello}).mappings().first()
            if not pick:
                modello_report["errore"] = "no_start_image"
                report.append(modello_report)
                continue

            start_url = pick["start_url"]
            img_bytes = download_with_retry(start_url)
            logging.info(f"✅ Download completato per {codice_modello}, size={len(img_bytes)} bytes")

            for scenario, prompt in SCENARIO_PROMPTS.items():
                foto = (
                    db.query(MnetModelliAIFoto)
                    .filter(
                        MnetModelliAIFoto.codice_modello == codice_modello,
                        MnetModelliAIFoto.scenario == scenario
                    )
                    .first()
                )

                if foto and foto.ai_foto_url:
                    logging.info(f"⏩ Skip {codice_modello} - {scenario}, già presente")
                    modello_report["scenari"][scenario] = "skip"
                    continue

                logging.info(f"▶️ Inizio generazione {codice_modello} - {scenario}")

                try:
                    png_bytes = await _nano_banana_generate_image(scenario, prompt, img_bytes)
                    webp_bytes = _to_webp(png_bytes)
                    fname = f"{codice_modello}/{scenario}-{uuid.uuid4()}.webp"
                    storage_path, public_url = _sb_upload_and_sign_bucket(fname, webp_bytes, "image/webp")

                    if not foto:
                        foto = MnetModelliAIFoto(codice_modello=codice_modello, scenario=scenario)
                        db.add(foto)

                    foto.ai_foto_url = public_url
                    foto.ai_foto_prompt = prompt
                    foto.ai_foto_updated_at = datetime.utcnow()
                    db.commit()

                    modello_report["scenari"][scenario] = "ok"
                except Exception as e:
                    logging.exception(f"❌ Errore {codice_modello} - {scenario}")
                    modello_report["scenari"][scenario] = f"errore: {e}"

        except Exception as e:
            modello_report["errore"] = str(e)

        report.append(modello_report)

    logging.info("🎯 Fine sync immagini AI mnet")
    return {"status": "completed", "report": report}

