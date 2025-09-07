# app/routes/moviepy.py
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from moviepy.editor import ColorClip
import io

router = APIRouter(prefix="/api/test", tags=["Test"])

@router.get("/moviepy")
def test_moviepy():
    """Genera un MP4 rosso 1080x1920 di 2 secondi e lo restituisce subito come risposta."""
    # Clip di test
    clip = ColorClip(size=(1080, 1920), color=(255, 0, 0), duration=2).set_fps(24)

    # Scriviamo in memoria invece che su disco
    buf = io.BytesIO()
    clip.write_videofile(
        "test.mp4",  # nome temporaneo richiesto da moviepy
        codec="libx264",
        audio=False,
        fps=24,
        temp_audiofile="temp-audio.m4a",
        remove_temp=True,
        threads=2,
        logger=None  # silenzia output
    )

    clip.close()

    # Riapri il file appena scritto
    with open("test.mp4", "rb") as f:
        buf.write(f.read())

    buf.seek(0)
    return StreamingResponse(buf, media_type="video/mp4")
