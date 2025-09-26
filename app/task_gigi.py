# tasks_gigi.py
import logging, os
from io import BytesIO
from PIL import Image
from sqlalchemy.orm import Session
from sqlalchemy import text  # ✅ fix SQLAlchemy
from app.database import SessionLocal, supabase_client
from app.routes.gigigorilla import expand_aliases  
from app.routes.openai_config import (
    _gemini_generate_image_sync,
    _fetch_image_base64_from_url,
    _gemini_assert_api
)

def _apply_logo(final: Image.Image, logo_url: str, h: int, y: int) -> Image.Image:
    import requests
    r = requests.get(logo_url, timeout=30); r.raise_for_status()
    logo = Image.open(BytesIO(r.content)).convert("RGBA")
    ow, oh = logo.size
    new_h = max(1, int(h or 100)); new_w = int((ow/oh)*new_h)
    logo = logo.resize((new_w, new_h))
    if final.height < new_h + y: raise ValueError(f"image too small for logo offset {y}px")
    final.paste(logo, ((final.width-new_w)//2, y), logo)
    return final

def _sb_upload_and_sign_to(bucket: str, path: str, blob: bytes, content_type: str) -> str:
    supabase_client.storage.from_(bucket).upload(path=path, file=blob,
        file_options={"content-type": content_type, "upsert":"true"})
    res = supabase_client.storage.from_(bucket).create_signed_url(path=path, expires_in=60*60*24*30)
    url = res.get("signedURL") or res.get("signed_url") or res.get("signedUrl")
    base = os.getenv("SUPABASE_URL","").rstrip("/")
    return f"{base}{url}" if url and url.startswith("/storage") else url

async def processa_gigi_gorilla_jobs():
    db: Session = SessionLocal()
    try:
        rows = db.execute(text("""
            select * from public.gigi_gorilla_jobs
            where status='queued'
            order by created_at asc
            for update skip locked
        """)).fetchall()

        for j in rows:
            db.execute(text("""
                update public.gigi_gorilla_jobs
                set status='processing'
                where id=:id
            """), {"id": j.id})
            db.commit()

            try:
                _gemini_assert_api()

                # 👇 espandi alias PRIMA della generazione, fallback al prompt originale in caso di errore
                try:
                    prompt_for_engine = expand_aliases(j.prompt or "", db=db)
                except Exception:
                    prompt_for_engine = j.prompt

                imgs = await _gemini_generate_image_sync(
                    prompt_for_engine,
                    subject_image_url=j.subject_url,
                    background_image_url=j.background_url,
                    num_images=j.num_images
                )

                done = 0
                for i, img_bytes in enumerate(imgs):
                    img = Image.open(BytesIO(img_bytes)).convert("RGBA")
                    if j.logo_url:
                        img = _apply_logo(img, j.logo_url, j.logo_height or 100, j.logo_offset_y or 100)

                    buf = BytesIO()
                    if j.output_format == "webp":
                        img.save(buf, format="WEBP", quality=90)
                        mime = "image/webp"
                        ext = ".webp"
                    else:
                        img.save(buf, format="PNG")
                        mime = "image/png"
                        ext = ".png"
                    buf.seek(0)

                    path = f"{j.storage_prefix}{j.id}/{i}{ext}"
                    url = _sb_upload_and_sign_to(j.bucket, path, buf.getvalue(), mime)

                    db.execute(text("""
                        insert into public.gigi_gorilla_job_outputs
                            (job_id, idx, status, public_url, storage_path, mime_type, width, height)
                        values
                            (:job, :idx, 'completed', :url, :path, :mime, :w, :h)
                    """), {
                        "job": j.id, "idx": i, "url": url, "path": path, "mime": mime,
                        "w": img.width, "h": img.height
                    })
                    done += 1

                new_status = 'completed' if done >= j.num_images else 'queued'
                db.execute(text("""
                    update public.gigi_gorilla_jobs
                    set status = :st,
                        retry_count = case when :st = 'completed' then retry_count else retry_count + 1 end
                    where id = :id
                """), {"st": new_status, "id": j.id})
                db.commit()

            except Exception as e:
                db.rollback()
                db.execute(text("""
                    update public.gigi_gorilla_jobs
                    set status = 'failed',
                        error_message = :err,
                        retry_count = retry_count + 1
                    where id = :id
                """), {"id": j.id, "err": str(e)})
                db.commit()
                logging.error(f"Gigi job {j.id} failed: {e}")

    finally:
        db.close()

