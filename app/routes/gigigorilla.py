# gigigorilla.py
from fastapi import APIRouter, Depends, HTTPException
from fastapi_jwt_auth import AuthJWT
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy.orm import Session
from app.database import get_db, supabase_client
from app.models import User
from uuid import UUID as _UUID
import os, base64
from io import BytesIO
from PIL import Image
from sqlalchemy import text


# riusa util di Gemini già presenti
from app.routes.openai_config import _gemini_generate_image_sync

router = APIRouter()
GIGI_CREDIT_COST = float(os.getenv("GIGI_CREDIT_COST", "1.5"))

ALLOWED_Q = {"low","medium","high","auto","standard","hd"}
ALLOWED_ORIENT = {"square","landscape","portrait"}
SIZE_MAP = {"square":"1024x1024","landscape":"1792x1024","portrait":"1024x1792"}

def _sb_upload_and_sign_to(bucket: str, path: str, blob: bytes, content_type: str) -> str:
    supabase_client.storage.from_(bucket).upload(path=path, file=blob,
        file_options={"content-type": content_type, "upsert":"true"})
    res = supabase_client.storage.from_(bucket)\
        .create_signed_url(path=path, expires_in=60*60*24*30)
    url = res.get("signedURL") or res.get("signed_url") or res.get("signedUrl")
    base = os.getenv("SUPABASE_URL","").rstrip("/")
    return f"{base}{url}" if url and url.startswith("/storage") else url

class GigiJobCreate(BaseModel):
    prompt: str = Field(min_length=3)
    subject_url: HttpUrl | None = None
    background_url: HttpUrl | None = None
    logo_url: HttpUrl | None = None
    logo_height: int = 100
    logo_offset_y: int = 100
    num_images: int = Field(1, ge=1, le=4)
    quality: str = "medium"            # low|medium|high|auto|standard|hd
    orientation: str = "square"        # square|landscape|portrait
    output_format: str = "png"         # png|webp

class GigiJobCreated(BaseModel):
    job_id: _UUID
    status: str = "queued"

class GigiJobStatus(BaseModel):
    job_id: _UUID
    status: str
    outputs: list[str] = []
    error_message: str | None = None

@router.post("/ai/gigi-gorilla/jobs", response_model=GigiJobCreated)
def create_job(payload: GigiJobCreate, Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    Authorize.jwt_required()
    email = Authorize.get_jwt_subject()
    user = db.query(User).filter(User.email == email).first()
    if not user: raise HTTPException(403, "Utente non trovato")

    q = payload.quality.lower()
    if q not in ALLOWED_Q: raise HTTPException(400, "quality non valida")
    q = {"standard":"medium","hd":"high"}.get(q, q)

    if payload.orientation not in ALLOWED_ORIENT:
        raise HTTPException(400, "orientation non valida")

    # scala credito se dealer (riusa tua is_dealer_user)
    from app.auth_helpers import is_dealer_user
    if is_dealer_user(user):
        tot = GIGI_CREDIT_COST * payload.num_images
        if (user.credit or 0) < tot: raise HTTPException(402, "Credito insufficiente")
        user.credit = float(user.credit or 0) - tot
        from app.models import CreditTransaction
        db.add(CreditTransaction(dealer_id=user.id, amount=-tot, transaction_type="USE",
                                 note=f"Gigi Gorilla x{payload.num_images}"))

    # insert job
    size = SIZE_MAP[payload.orientation]
    storage_prefix = f"{user.id}/"  # base path
    job_id = db.execute(text("""
        insert into public.gigi_gorilla_jobs
          (user_id, prompt, subject_url, background_url, logo_url, logo_height, logo_offset_y,
           num_images, quality, orientation, output_format, aspect_ratio, size, status, bucket, storage_prefix)
        values
          (:uid, :p, :s, :b, :l, :lh, :lo, :n, :q, :o, :f,
           case when :o='square' then '1:1' when :o='landscape' then '16:9' else '9:16' end,
           :size, 'queued', 'gigi-gorilla', :pref)
        returning id
    """), {
        "uid": user.id, "p": payload.prompt, "s": payload.subject_url, "b": payload.background_url,
        "l": payload.logo_url, "lh": payload.logo_height, "lo": payload.logo_offset_y,
        "n": payload.num_images, "q": q, "o": payload.orientation, "f": payload.output_format,
        "size": size, "pref": storage_prefix
    }).scalar()

    db.commit()
    return GigiJobCreated(job_id=job_id)

@router.get("/ai/gigi-gorilla/jobs/{job_id}", response_model=GigiJobStatus)
def job_status(job_id: _UUID, Authorize: AuthJWT = Depends(), db: Session = Depends(get_db)):
    Authorize.jwt_required()
    email = Authorize.get_jwt_subject()
    user = db.query(User).filter(User.email == email).first()
    if not user: raise HTTPException(403, "Utente non trovato")

    row = db.execute("""
      select id, user_id, status, error_message
      from public.gigi_gorilla_jobs where id=:id
    """, {"id": job_id}).first()
    if not row or row.user_id != user.id: raise HTTPException(404, "Job non trovato")

    outs = db.execute("""
      select public_url from public.gigi_gorilla_job_outputs
      where job_id=:id and status='completed' order by idx
    """, {"id": job_id}).scalars().all()

    return GigiJobStatus(job_id=row.id, status=row.status, outputs=outs, error_message=row.error_message)
