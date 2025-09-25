from fastapi import APIRouter, Depends, HTTPException
from fastapi_jwt_auth import AuthJWT
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy.orm import Session
from app.database import get_db, supabase_client
from app.models import User
from uuid import UUID as _UUID

import os
import base64
import uuid
from sqlalchemy import text

# helpers ruoli
from app.auth_helpers import is_dealer_user

# riusa util di Gemini già presenti
from app.routes.openai_config import _gemini_generate_image_sync
from app.openai_utils import genera_descrizione_gpt


router = APIRouter()

GIGI_CREDIT_COST = float(os.getenv("GIGI_CREDIT_COST", "1.5"))

ALLOWED_Q = {"low", "medium", "high", "auto", "standard", "hd"}
ALLOWED_ORIENT = {"square", "landscape", "portrait"}
SIZE_MAP = {
    "square": "1024x1024",
    "landscape": "1792x1024",
    "portrait": "1024x1792",
}

# --------- MODELS ----------

class GigiJobCreate(BaseModel):
    prompt: str = Field(min_length=3)

    # Modalità URL (attuale)
    subject_url: HttpUrl | None = None
    background_url: HttpUrl | None = None
    logo_url: HttpUrl | None = None

    # Modalità base64 (nuova)
    subject_base64: str | None = None
    background_base64: str | None = None
    logo_base64: str | None = None

    logo_height: int = 100
    logo_offset_y: int = 100
    num_images: int = Field(1, ge=1, le=4)
    quality: str = "medium"
    orientation: str = "square"
    output_format: str = "png"


class GigiJobCreated(BaseModel):
    job_ids: list[_UUID]
    status: str = "queued"


class GigiJobStatus(BaseModel):
    job_id: _UUID
    status: str
    outputs: list[str] = []
    error_message: str | None = None

def upload_base64_to_supabase(base64_data: str, user_id: str, label: str) -> str:
    """
    Carica un'immagine codificata in base64 nello storage Supabase e restituisce l'URL pubblico.
    - base64_data: stringa con o senza prefisso data:image/...
    - user_id: id dell'utente (usato come prefisso cartella)
    - label: 'subject', 'background' o 'logo'
    """

    # 🔹 rimuove eventuale prefisso data:image/...
    if "," in base64_data:
        base64_data = base64_data.split(",")[1]

    try:
        binary = base64.b64decode(base64_data)
    except Exception as e:
        raise ValueError(f"Base64 non valido: {e}")

    # 🔹 nome file unico
    filename = f"{user_id}/{label}-{uuid.uuid4().hex}.png"

    try:
        # upload senza upsert (non supportato dalla SDK Python)
        supabase_client.storage.from_("gigi-gorilla").upload(
            path=filename,
            file=binary,
            file_options={"content-type": "image/png"}
        )
    except Exception as e:
        raise RuntimeError(f"Errore upload su Supabase: {e}")

    # 🔹 genera URL pubblico
    try:
        public_url = supabase_client.storage.from_("gigi-gorilla").get_public_url(filename)
    except Exception as e:
        raise RuntimeError(f"Errore generazione URL pubblico: {e}")

    return public_url



async def genera_varianti_prompt(prompt_base: str, num_variants: int = 3) -> list[str]:
    """
    Genera varianti visive di un prompt di input usando GPT.
    Restituisce una lista di stringhe diverse, lunghezza = num_variants (o meno se GPT ne produce di meno).
    """
    # Prompt per GPT
    prompt_llm = (
        f"Prompt originale: \"{prompt_base}\"\n\n"
        f"Genera {num_variants} prompt diversi per la generazione di immagini AI.\n"
        "Ogni variante deve mantenere il soggetto principale, ma cambiare almeno uno di questi aspetti: "
        "angolazione, composizione, stile, azione o contesto visivo.\n"
        "Rispondi solo con un elenco di frasi, una per riga, senza numeri o testo extra."
    )

    try:
        raw = await genera_descrizione_gpt(
            prompt=prompt_llm,
            max_tokens=600,
            temperature=0.85,
            model="gpt-4o"
        )
    except Exception as e:
        raise RuntimeError(f"Errore generazione prompt varianti: {e}")

    # Cleanup: normalizza in lista
    variants = [line.strip("-•*– ").strip() for line in raw.splitlines() if line.strip()]
    return variants[:num_variants] if variants else [prompt_base] * num_variants


# --------- CREATE JOB ----------

@router.post("/jobs", response_model=GigiJobCreated)
async def create_job(
    payload: GigiJobCreate,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    email = Authorize.get_jwt_subject()
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(403, "Utente non trovato")

    q = payload.quality.lower()
    if q not in ALLOWED_Q:
        raise HTTPException(400, "quality non valida")
    q = {"standard": "medium", "hd": "high"}.get(q, q)

    if payload.orientation not in ALLOWED_ORIENT:
        raise HTTPException(400, "orientation non valida")

    # scala credito se dealer
    if is_dealer_user(user):
        tot = GIGI_CREDIT_COST * payload.num_images
        if (user.credit or 0) < tot:
            raise HTTPException(402, "Credito insufficiente")
        user.credit = float(user.credit or 0) - tot
        from app.models import CreditTransaction
        db.add(
            CreditTransaction(
                dealer_id=user.id,
                amount=-tot,
                transaction_type="USE",
                note=f"Gigi Gorilla x{payload.num_images}",
            )
        )

    # --- Prompt variants se num_images > 1 ---
    if payload.num_images > 1:
        # genera N prompt diversi usando GPT
        prompt_variants = await genera_varianti_prompt(payload.prompt, payload.num_images)
    else:
        prompt_variants = [payload.prompt]

    size = SIZE_MAP[payload.orientation]
    storage_prefix = f"{user.id}/"

    subject_url = payload.subject_url
    background_url = payload.background_url
    logo_url = payload.logo_url

    if payload.subject_base64:
        subject_url = upload_base64_to_supabase(payload.subject_base64, user.id, "subject")

    if payload.background_base64:
        background_url = upload_base64_to_supabase(payload.background_base64, user.id, "background")

    if payload.logo_base64:
        logo_url = upload_base64_to_supabase(payload.logo_base64, user.id, "logo")


    job_ids = []

    for i, prompt_variant in enumerate(prompt_variants):
        job_id = db.execute(
            text(
                """
                insert into public.gigi_gorilla_jobs
                  (user_id, prompt, subject_url, background_url, logo_url,
                   logo_height, logo_offset_y, num_images, quality, orientation,
                   output_format, aspect_ratio, size, status, bucket, storage_prefix)
                values
                  (:uid, :p, :s, :b, :l, :lh, :lo, :n, :q, :o, :f,
                   case when :o='square' then '1:1'
                        when :o='landscape' then '16:9'
                        else '9:16' end,
                   :size, 'queued', 'gigi-gorilla', :pref)
                returning id
                """
            ),
            {
                "uid": user.id,
                "p": prompt_variant,    # 👈 usa prompt variato
                "s": subject_url,
                "b": background_url,
                "l": logo_url,
                "lh": payload.logo_height,
                "lo": payload.logo_offset_y,
                "n": 1,                 # 👈 forza sempre 1 per Gemini
                "q": q,
                "o": payload.orientation,
                "f": payload.output_format,
                "size": SIZE_MAP[payload.orientation],
                "pref": f"{user.id}/",
            },
        ).scalar()

        job_ids.append(job_id)

    db.commit()

    return {"job_ids": job_ids, "status": "queued"}

# --------- JOB STATUS ----------

@router.get("/jobs/{job_id}", response_model=GigiJobStatus)
def job_status(
    job_id: _UUID,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    email = Authorize.get_jwt_subject()
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(403, "Utente non trovato")

    row = db.execute(
        text(
            """
        select id, user_id, status, error_message
        from public.gigi_gorilla_jobs
        where id = :id and user_id = :uid
        """
        ),
        {"id": job_id, "uid": user.id},
    ).first()
    if not row:
        raise HTTPException(404, "Job non trovato")

    outs = db.execute(
        text(
            """
        select public_url
        from public.gigi_gorilla_job_outputs
        where job_id = :id and status = 'completed'
        order by idx
        """
        ),
        {"id": job_id},
    ).scalars().all()

    return GigiJobStatus(
        job_id=row.id, status=row.status, outputs=outs, error_message=row.error_message
    )

# --------- GALLERY ----------

@router.get("/gallery")
def get_gallery(
    offset: int = 0,
    limit: int = 20,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    email = Authorize.get_jwt_subject()
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(403, "Utente non trovato")

    rows = db.execute(
        text(
            """
        select o.id as output_id,
               o.public_url,
               o.width,
               o.height,
               o.mime_type,
               o.created_at,
               j.prompt,
               j.id as job_id
        from public.gigi_gorilla_job_outputs o
        join public.gigi_gorilla_jobs j on j.id = o.job_id
        where j.user_id = :uid
        and o.status = 'completed'
        and o.is_deleted is not true
        order by o.created_at desc
        offset :off limit :lim
        """
        ),
        {"uid": user.id, "off": offset, "lim": limit},
    ).mappings().all()

    return {"items": [dict(r) for r in rows]}

from fastapi import status

@router.patch("/outputs/{output_id}/delete", status_code=status.HTTP_204_NO_CONTENT)
def soft_delete_output(
    output_id: _UUID,
    Authorize: AuthJWT = Depends(),
    db: Session = Depends(get_db)
):
    Authorize.jwt_required()
    email = Authorize.get_jwt_subject()
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(403, "Utente non trovato")

    result = db.execute(
        text("""
            update public.gigi_gorilla_job_outputs
            set is_deleted = true
            where id = :id and job_id in (
                select id from public.gigi_gorilla_jobs
                where user_id = :uid
            )
        """),
        {"id": output_id, "uid": user.id}
    )

    if result.rowcount == 0:
        raise HTTPException(404, "Output non trovato o accesso negato")

    db.commit()

