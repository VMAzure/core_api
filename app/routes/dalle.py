from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import Response
from openai import OpenAI
from io import BytesIO
from PIL import Image
import base64, requests, os
from uuid import uuid4
from datetime import datetime

router = APIRouter()

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    organization=os.getenv("OPENAI_ORG_ID")
)

QUALITY_MAP = {"standard": "medium", "hd": "high"}
ALLOWED_QUALITY = {"low", "medium", "high", "auto"}
ORIENTATION_SIZE = {
    "square": "1024x1024",
    "landscape": "1792x1024",
    "portrait": "1024x1792"
}

@router.post("/ai/dalle/combine")
async def dalle_combine(
    prompt: str = Form(...),

    img1_url: str = Form(...),
    img2_url: str = Form(...),

    quality: str = Form("medium"),
    orientation: str = Form("square"),

    logo_url: str = Form(None),
    logo_height: int = Form(100),
    logo_offset_y: int = Form(100),

    as_file: bool = Form(True),
):
    # --- qualità e orientamento ---
    q = QUALITY_MAP.get(quality.lower(), quality.lower())
    if q not in ALLOWED_QUALITY:
        raise HTTPException(400, "quality must be one of: low, medium, high, auto (or standard/hd)")
    if orientation not in ORIENTATION_SIZE:
        raise HTTPException(400, "orientation must be one of: square, landscape, portrait")
    size = ORIENTATION_SIZE[orientation]

    # --- carica immagini da URL ---
    def load_image_from_url(url: str, field: str):
        try:
            r = requests.get(url)
            r.raise_for_status()
            return Image.open(BytesIO(r.content)).convert("RGB")
        except Exception:
            raise HTTPException(400, f"Invalid image URL for '{field}'")

    i1 = load_image_from_url(img1_url, "img1_url")
    i2 = load_image_from_url(img2_url, "img2_url")

    # --- composizione orizzontale ---
    w, h = i1.width + i2.width, max(i1.height, i2.height)
    canvas = Image.new("RGB", (w, h), (255, 255, 255))
    canvas.paste(i1, (0, 0))
    canvas.paste(i2, (i1.width, 0))

    buf = BytesIO()
    canvas.save(buf, format="PNG")
    buf.seek(0)
    buf.name = "canvas.png"

    # --- chiamata a DALL·E ---
    try:
        res = client.images.edit(
            model="gpt-image-1",
            prompt=prompt,
            image=buf,
            size=size,
            quality=q,
        )
    except Exception as e:
        raise HTTPException(500, f"DALL·E error: {str(e)}")

    img_b64 = res.data[0].b64_json
    img_bytes = base64.b64decode(img_b64)
    final = Image.open(BytesIO(img_bytes)).convert("RGBA")

    # --- logo se presente ---
    if logo_url:
        try:
            r = requests.get(logo_url)
            r.raise_for_status()
            logo = Image.open(BytesIO(r.content)).convert("RGBA")

            ow, oh = logo.size
            new_h = logo_height
            new_w = int((ow / oh) * new_h)
            logo = logo.resize((new_w, new_h))

            if final.height < new_h + logo_offset_y:
                raise HTTPException(400, f"image too small for logo offset {logo_offset_y}px")

            logo_x = (final.width - new_w) // 2
            logo_y = logo_offset_y
            final.paste(logo, (logo_x, logo_y), logo)
        except Exception as e:
            raise HTTPException(400, f"logo_url error: {str(e)}")

    # --- output finale ---
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

    return {
        "message": "ok",
        "quality_used": q,
        "size": size,
        "orientation": orientation,
        "logo_applied": bool(logo_url),
    }
