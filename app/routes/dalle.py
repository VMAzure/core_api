# app/routes/dalle.py
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from openai import OpenAI
import os
from io import BytesIO
from PIL import Image

router = APIRouter()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

@router.post("/ai/dalle/combine")
async def dalle_combine(
    prompt: str = Form(...),
    img1: UploadFile = File(...),
    img2: UploadFile = File(...),
):
    try:
        # Leggi immagini
        i1 = Image.open(BytesIO(await img1.read()))
        i2 = Image.open(BytesIO(await img2.read()))

        # Canvas affiancato orizzontale
        w = i1.width + i2.width
        h = max(i1.height, i2.height)
        canvas = Image.new("RGB", (w, h), (255, 255, 255))
        canvas.paste(i1, (0, 0))
        canvas.paste(i2, (i1.width, 0))

        # Converti in buffer PNG
        buf = BytesIO()
        canvas.save(buf, format="PNG")
        buf.seek(0)

        # Invio a DALL·E 3
        result = client.images.edit(
            model="dall-e-3",
            prompt=prompt,
            image=buf,
            size="1024x1024"
        )

        return JSONResponse(content=result.data[0].model_dump())

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
