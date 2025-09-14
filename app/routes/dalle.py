# app/routes/dalle.py
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from openai import OpenAI
import os, base64
from io import BytesIO
from PIL import Image
from uuid import uuid4
from datetime import datetime

router = APIRouter()

client = OpenAI(
    api_key=os.getenv("OPENAI_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY"),
    organization=os.getenv("OPENAI_ORG_ID")
)

QUALITY_MAP = {
    "standard": "medium",
    "hd": "high"
}
ALLOWED_QUALITY = {"low", "medium", "high", "auto"}

@router.post("/ai/dalle/combine")
async def dalle_combine(
    prompt: str = Form(...),
    img1: UploadFile = File(...),
    img2: UploadFile = File(...),
    quality: str = Form("medium"),   # default coerente con gpt-image-1
    size: str = Form("1024x1024")
):
    try:
        q = QUALITY_MAP.get(quality.lower(), quality.lower())
        if q not in ALLOWED_QUALITY:
            raise HTTPException(status_code=400, detail="quality must be one of: low, medium, high, auto (or standard/hd which map to medium/high)")

        # Leggi e normalizza immagini
        i1 = Image.open(BytesIO(await img1.read())).convert("RGB")
        i2 = Image.open(BytesIO(await img2.read())).convert("RGB")

        # Canvas affiancato orizzontale
        w, h = i1.width + i2.width, max(i1.height, i2.height)
        canvas = Image.new("RGB", (w, h), (255, 255, 255))
        canvas.paste(i1, (0, 0))
        canvas.paste(i2, (i1.width, 0))

        # Buffer PNG nominato (serve a OpenAI per il mimetype)
        buf = BytesIO()
        canvas.save(buf, format="PNG")
        buf.seek(0)
        buf.name = "canvas.png"

        # Chiamata a gpt-image-1 (images.edit ritorna sempre b64_json)
        result = client.images.edit(
            model="gpt-image-1",
            prompt=prompt,
            image=buf,
            size=size,
            quality=q
        )

        # Decodifica e salvataggio locale per test
        img_b64 = result.data[0].b64_json
        img_bytes = base64.b64decode(img_b64)

        out_dir = os.getenv("IMG_OUT_DIR", "tmp")
        os.makedirs(out_dir, exist_ok=True)
        fname = f"dalle_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}.png"
        out_path = os.path.join(out_dir, fname)
        with open(out_path, "wb") as f:
            f.write(img_bytes)

        return JSONResponse({
            "message": "ok",
            "quality_used": q,
            "size": size,
            "local_path": out_path
        })

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
