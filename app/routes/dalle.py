# app/routes/dalle.py
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import Response, JSONResponse
from openai import OpenAI
from io import BytesIO
from PIL import Image
from uuid import uuid4
from datetime import datetime
import os, base64

router = APIRouter()

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    organization=os.getenv("OPENAI_ORG_ID"),
)

QUALITY_MAP = {"standard": "medium", "hd": "high"}
ALLOWED_QUALITY = {"low", "medium", "high", "auto"}
ALLOWED_SIZE = {"1024x1024", "1792x1024", "1024x1792"}

@router.post(
    "/ai/dalle/combine",
    responses={
        200: {
            "content": {
                "image/png": {},
                "application/json": {}
            },
            "description": "PNG file or JSON"
        }
    },
)
async def dalle_combine(
    prompt: str = Form(...),
    img1: UploadFile = File(...),
    img2: UploadFile = File(...),
    quality: str = Form("medium"),          # accetta: low|medium|high|auto anche standard|hd
    size: str = Form("1024x1024"),          # ammessi: 1024x1024 | 1792x1024 | 1024x1792
    as_file: bool = Form(True),             # True => ritorna PNG diretto (Swagger: “Download file”)
    temperature=0.1   # ← ottimale per realismo controllato

):
    # normalizza qualità
    q = QUALITY_MAP.get(quality.lower(), quality.lower())
    if q not in ALLOWED_QUALITY:
        raise HTTPException(400, "quality must be one of: low, medium, high, auto (or standard/hd)")
    if size not in ALLOWED_SIZE:
        raise HTTPException(400, f"size must be one of: {', '.join(sorted(ALLOWED_SIZE))}")

    # leggi e combina le due immagini
    try:
        i1 = Image.open(BytesIO(await img1.read())).convert("RGB")
        i2 = Image.open(BytesIO(await img2.read())).convert("RGB")
    except Exception:
        raise HTTPException(400, "invalid image input")

    w, h = i1.width + i2.width, max(i1.height, i2.height)
    canvas = Image.new("RGB", (w, h), (255, 255, 255))
    canvas.paste(i1, (0, 0))
    canvas.paste(i2, (i1.width, 0))

    # buffer PNG nominato (mimetype hint per OpenAI)
    buf = BytesIO()
    canvas.save(buf, format="PNG")
    buf.seek(0)
    buf.name = "canvas.png"

    # chiamata a gpt-image-1 (images.edit restituisce base64)
    try:
        res = client.images.edit(
            model="gpt-image-1",
            prompt=prompt,
            image=buf,
            size=size,
            quality=q,
        )
    except Exception as e:
        # propaghiamo errore API in modo chiaro
        raise HTTPException(500, detail=str(e))

    img_b64 = res.data[0].b64_json
    img_bytes = base64.b64decode(img_b64)

    if as_file:
        fname = f"dalle_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}.png"
        return Response(
            content=img_bytes,
            media_type="image/png",
            headers={
                "Content-Disposition": f'inline; filename="{fname}"',
                "X-Image-Size": size,
                "X-Image-Quality": q,
            },
        )

    # fallback JSON (utile se vuoi gestire lato frontend o salvare altrove)
    return JSONResponse({
        "message": "ok",
        "quality_used": q,
        "size": size,
        "b64_json": img_b64,  # attenzione: grande
    })
