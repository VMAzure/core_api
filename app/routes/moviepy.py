import io
import tempfile
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from moviepy.video.VideoClip import ColorClip

router = APIRouter(prefix="/moviepy", tags=["Test"])

@router.get("/test")
def test_moviepy():
    """
    Generates a 2-second red MP4 video (1080x1920) and returns it as a streaming response.
    This version uses a secure temporary file to avoid disk I/O conflicts.
    """
    try:
        # 1. Create the clip and assign the FPS attribute directly.
        clip = ColorClip(size=(1080, 1920), color=(255, 0, 0), duration=2)
        clip.fps = 24

        # 2. Use a named temporary file to securely write the video to disk.
        # The 'with' block ensures the file is automatically deleted afterward.
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=True) as temp_video_file:
            temp_filename = temp_video_file.name
            
            # Write the video file to the unique temporary path
            clip.write_videofile(
                temp_filename,
                codec="libx264",
                audio=False,
                fps=24,
                threads=2,
                logger=None  # Suppress console output
            )
            
            # 3. Read the bytes from the temporary file to send them in the response.
            temp_video_file.seek(0)
            video_bytes = temp_video_file.read()

        # Return the video bytes in a streaming response
        return StreamingResponse(io.BytesIO(video_bytes), media_type="video/mp4")

    finally:
        # Ensure the clip resources are released, even if an error occurs.
        if 'clip' in locals():
            clip.close()


# app/routes/video_logo.py
import io
import tempfile
import requests
from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import StreamingResponse
from moviepy.video.VideoClip import VideoFileClip, ImageClip, CompositeVideoClip
import numpy as np
from PIL import Image

router = APIRouter(prefix="/video", tags=["Video"])

def download_file(url: str, suffix: str) -> str:
    """Scarica un file da URL e lo salva in un file temporaneo."""
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Download fallito: {e}")
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp.write(resp.content)
    tmp.flush()
    return tmp.name

@router.get("/add-logo")
def add_logo(
    video_url: str = Query(..., description="URL pubblico del video (Supabase)"),
    logo_url: str = Query(..., description="URL pubblico del logo PNG (Supabase)")
):
    """
    Inserisce il logo PNG dentro il video.
    - Il logo compare dopo 1s con una transizione (fade-in).
    - Restituisce direttamente l'MP4 come StreamingResponse.
    """
    try:
        # Scarica video e logo
        video_path = download_file(video_url, ".mp4")
        logo_path = download_file(logo_url, ".png")

        # Carica video
        clip = VideoFileClip(video_path)

        # Carica logo con PIL per preservare trasparenza
        logo_img = Image.open(logo_path).convert("RGBA")
        logo_np = np.array(logo_img)

        # Clip logo (durata = durata video, parte da 1s)
        logo_clip = (
            ImageClip(logo_np)
            .set_duration(clip.duration - 1)
            .set_start(1)              # inizia dopo 1 secondo
            .crossfadein(0.5)          # fade-in di mezzo secondo
            .set_position(("right", "top"))
            .resize(width=150)         # ridimensiona a 150px larghezza
            .set_opacity(0.9)
        )

        # Composizione
        final = CompositeVideoClip([clip, logo_clip])

        # Scrittura in buffer
        buf = io.BytesIO()
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=True) as tmp_out:
            final.write_videofile(
                tmp_out.name,
                codec="libx264",
                audio_codec="aac",
                fps=clip.fps or 24,
                threads=2,
                logger=None
            )
            tmp_out.seek(0)
            buf.write(tmp_out.read())

        buf.seek(0)
        return StreamingResponse(buf, media_type="video/mp4")

    finally:
        # cleanup risorse
        if "clip" in locals():
            clip.close()
        if "final" in locals():
            final.close()

