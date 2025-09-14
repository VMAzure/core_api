from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import Response
from openai import OpenAI
from io import BytesIO
from PIL import Image
import base64, requests, os
from uuid import uuid4
from datetime import datetime

router = APIRouter()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"),
                organization=os.getenv("OPENAI_ORG_ID"))

QUALITY_MAP = {"standard": "medium", "hd": "high"}
ALLOWED_QUALITY = {"low", "medium", "high", "auto"}
ALLOWED_SIZE = {"1024x1024", "1792x1024", "1024x1792"}

@router.post("/ai/dalle/combine")
async def dalle_combine(
    prompt: str = Form(...),
    img1: UploadFile = File(...),
    img2: UploadFile = File(...),
    quality: str = Form("medium"),
    size: str = Form("1024x1024"),
    logo_url: str = Form(None),
    logo_height: int = Form(100),        # 👈 altezza logo
    as_file: bool = Form(True),
):

    q = QUALITY_MAP.get(quality.lower(), quality.lower())
    if q not in ALLOWED_QUALITY:
        raise HTTPException(400, "quality must be one of: low, medium, high, auto (or standard/hd)")
    if size not in ALLOWED_SIZE:
        raise HTTPException(400, f"size must be one of: {', '.join(sorted(ALLOWED_SIZE))}")

    try:
        i1 = Image.open(BytesIO(await img1.read())).convert("RGB")
        i2 = Image.open(BytesIO(await img2.read())).convert("RGB")
    except Exception:
        raise HTTPException(400, "invalid image input")

    w, h = i1.width + i2.width, max(i1.height, i2.height)
    canvas = Image.new("RGB", (w, h), (255, 255, 255))
    canvas.paste(i1, (0, 0))
    canvas.paste(i2, (i1.width, 0))

    buf = BytesIO()
    canvas.save(buf, format="PNG")
    buf.seek(0)
    buf.name = "canvas.png"

    try:
        res = client.images.edit(
            model="gpt-image-1",
            prompt=prompt,
            image=buf,
            size=size,
            quality=q,
        )
    except Exception as e:
        raise HTTPException(500, detail=f"DALL·E error: {str(e)}")

    img_b64 = res.data[0].b64_json
    img_bytes = base64.b64decode(img_b64)
    final = Image.open(BytesIO(img_bytes)).convert("RGBA")

    # Applica logo se presente
        # Applica logo se presente
    if logo_url:
        try:
            r = requests.get(logo_url)
            r.raise_for_status()
            logo = Image.open(BytesIO(r.content)).convert("RGBA")

            # Resize: altezza fissa, larghezza auto
            original_w, original_h = logo.size
            aspect_ratio = original_w / original_h
            new_h = logo_height
            new_w = int(aspect_ratio * new_h)
            logo = logo.resize((new_w, new_h))

            # Verifica altezza minima immagine
            if final.height < new_h:
                raise HTTPException(400, f"image too small for logo height {new_h}px")

            # Posizionamento: top centrato
            logo_x = (final.width - new_w) // 2
            logo_y = 0

            final.paste(logo, (logo_x, logo_y), logo)

        except Exception as e:
            raise HTTPException(400, f"logo_url error: {str(e)}")


    output = BytesIO()
    final.save(output, format="PNG")
    output.seek(0)

    if as_file:
        fname = f"dalle_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}.png"
        return Response(
            content=output.read(),
            media_type="image/png",
            headers={"Content-Disposition": f'inline; filename="{fname}"'}
        )

    # JSON fallback
    return {
        "message": "ok",
        "quality_used": q,
        "size": size,
        "logo_applied": bool(logo_url),
    }
