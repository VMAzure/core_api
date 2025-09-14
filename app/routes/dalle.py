from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from openai import OpenAI
import os
from io import BytesIO
from PIL import Image
import base64

router = APIRouter()

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    organization=os.getenv("OPENAI_ORG_ID")  # opzionale, utile se hai più org
)

@router.post("/ai/dalle/combine")
async def dalle_combine(
    prompt: str = Form(...),
    img1: UploadFile = File(...),
    img2: UploadFile = File(...),
    quality: str = Form("standard"),   # "standard" oppure "hd"
):
    try:
        if quality not in ["standard", "hd"]:
            raise HTTPException(status_code=400, detail="quality must be 'standard' or 'hd'")

        # Leggi immagini
        i1 = Image.open(BytesIO(await img1.read()))
        i2 = Image.open(BytesIO(await img2.read()))

        # Canvas affiancato orizzontale
        w = i1.width + i2.width
        h = max(i1.height, i2.height)
        canvas = Image.new("RGB", (w, h), (255, 255, 255))
        canvas.paste(i1, (0, 0))
        canvas.paste(i2, (i1.width, 0))

        # Converti in buffer PNG con nome
        buf = BytesIO()
        canvas.save(buf, format="PNG")
        buf.seek(0)
        buf.name = "canvas.png"

        # Invio a GPT Image 1 (DALL·E 3)
        result = client.images.edit(
            model="gpt-image-1",
            prompt=prompt,
            image=buf,
            size="1024x1024",
            quality=quality,
            response_format="b64_json"  # 👈 chiediamo base64
        )

        # Decodifica base64 e salva su file locale
        img_b64 = result.data[0].b64_json
        img_bytes = base64.b64decode(img_b64)

        output_dir = "tmp"
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, "output.png")
        with open(output_path, "wb") as f:
            f.write(img_bytes)

        return {
            "message": "Immagine generata",
            "local_path": output_path,
            "base64_preview": img_b64[:200] + "..."  # preview corta, non tutto il base64
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
