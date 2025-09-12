from fastapi import APIRouter, Depends, HTTPException
from fastapi_jwt_auth import AuthJWT
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session
from datetime import datetime
import uuid, io, os, logging
from PIL import Image
import time

from app.database import get_db, supabase_client
from app.models import MnetModelli, MnetModelliAIFoto
from app.routes.openai_config import _gemini_generate_image_sync  # async

router = APIRouter(tags=["Modelli AI - Test"])

SUPABASE_BUCKET_MODELLI_AI = os.getenv("SUPABASE_BUCKET_MODELLI_AI", "modelli-ai")
WEBP_QUALITY = int(os.getenv("MODEL_AI_WEBP_QUALITY", "90"))

SCENARIO_PROMPTS = {
    "indoor": """Fotografia cinematografica ultra realistica della stessa auto mostrata nell’immagine caricata. Mantieni fedelmente forma, proporzioni, colore e loghi originali. Scatto con lente 85mm, prospettiva naturale e profondità di campo realistica. Ambientata in un showroom auto premium reale, con pavimento riflettente e grandi vetrate che lasciano intravedere fuori si vede la città commerciale viva ed illuminata a giorno. Illuminazione cinematografica indoor con riflessi realistici sulla carrozzeria, luce HDR da esposizione. L’auto deve occupare almeno il 75% della larghezza dell’immagine, in primo piano senza ostacoli. La targa deve essere bianca con scritta AZURE in carattere Sans, centrata e senza distorsioni. Stile fotografico professionale, nessun effetto rendering, nessun watermark o testo extra.""",
    "mediterraneo": """Partendo dalla foto caricata, genera una nuova immagine fotorealistica dell’auto. Mantieni forma, proporzioni, rispetta l'angolo di visuale che ha l'immagine caricata, colore e loghi originali. Ambientala in un borgo antico di un'isola mediterranea con vista sul porto al mare con barche e pescherecci, parcheggiata davanti a una trattoria antica con tovaglie a quadretti bianchi e rossi, lucine colorate e illuminazione calda e persone ben vestite sedute a fare aperitivi. Inquadra con lente 85mm; l’auto deve essere in primo piano grande senza nulla davanti e occupare almeno il 75% della larghezza dell’immagine. Luce cinematografica al tramonto con riflessi realistici sulla carrozzeria. La targa deve essere bianca con la scritta AZURE con carattere stile Sans; centrata e senza distorsioni. Nessun testo extra, watermark o caratteri non latini.""",
    "cortina": """Partendo dalla foto caricata, genera una nuova immagine fotorealistica dell’auto. Mantieni forma, proporzioni, rispetta l'angolo di visuale che ha l'immagine caricata, colore e loghi originali. Ambientala in una località sciistica modaiola fashion , in centro città con negozi e hotel tipici alpini. la molta neve amplifica l'illuminazione. Inquadra con lente 85mm; l’auto deve essere in primo piano grande senza nulla davanti e occupare almeno il 75% della larghezza dell’immagine. Luce cinematografica di sera con riflessi realistici sulla carrozzeria. La targa deve essere bianca con la scritta AZURE con carattere stile Sans; centrata e senza distorsioni. Nessun testo extra, watermark o caratteri non latini.""",
    "milano": """Partendo dalla foto caricata, genera una nuova immagine fotorealistica dell’auto. Mantieni forma, proporzioni, colore e loghi originali. Ambientala in una città metropolitana tipo milano elegante e fashion, con ristoranti, alberi e movida sullo sfondo. Inquadra con lente 85mm; l’auto deve essere in primo piano e occupare almeno il 75% della larghezza dell’immagine. Luce cinematografica al tramonto con riflessi realistici sulla carrozzeria. La targa deve essere bianca con la scritta AZURE con carattere stile logo; centrata e senza distorsioni. Nessun testo extra, watermark o caratteri non latini.""",
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

class ModelloAITestRequest(BaseModel):
    codice_modello: str | None = None
    start_image_url: str | None = None
    scenario: str = "indoor"   # indoor | mediterraneo | cortina | milano

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
    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=WEBP_QUALITY)
    return buf.getvalue()

@router.post("/modelli-ai/test", response_model=ModelloAITestResponse)
async def modelli_ai_test(
    payload: ModelloAITestRequest,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()

    # valida scenario e seleziona prompt
    scenario = (payload.scenario or "indoor").lower().strip()
    if scenario not in SCENARIO_PROMPTS:
        raise HTTPException(422, f"Scenario non valido: {scenario}")
    used_prompt = SCENARIO_PROMPTS[scenario]

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
            codice_modello = "MANUALE"

    # 2) Download robusto
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
        raise HTTPException(424, f"Impossibile scaricare immagine dopo {retries} tentativi. Ultimo errore: {last_err}")

    try:
        img_bytes = download_with_retry(start_url)
    except Exception as e:
        raise HTTPException(424, f"Impossibile scaricare immagine iniziale. Errore: {e}")

    # 3) Gemini
    png_bytes = await _gemini_generate_image_sync(
        prompt=used_prompt,
        start_image_bytes=img_bytes
    )

    # 4) WEBP + upload
    webp_bytes = _to_webp(png_bytes)
    fname = f"{codice_modello}/{uuid.uuid4()}.webp"
    storage_path, public_url = _sb_upload_and_sign_bucket(fname, webp_bytes, "image/webp")

    # 5) Persistenza scenario
    saved = False
    if codice_modello != "MANUALE":
        rec = db.query(MnetModelli).filter(MnetModelli.codice_modello == codice_modello).first()
        if not rec:
            raise HTTPException(404, f"Modello {codice_modello} non trovato per il salvataggio.")

        foto = (
            db.query(MnetModelliAIFoto)
            .filter(
                MnetModelliAIFoto.codice_modello == codice_modello,
                MnetModelliAIFoto.scenario == scenario
            )
            .first()
        )
        if not foto:
            foto = MnetModelliAIFoto(codice_modello=codice_modello, scenario=scenario)
            db.add(foto)

        foto.ai_foto_url = public_url
        foto.ai_foto_prompt = used_prompt
        foto.ai_foto_updated_at = datetime.utcnow()
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