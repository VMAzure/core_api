# app/routes/video_maker.py
import io
import os
import tempfile
from io import BytesIO

import requests
from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import StreamingResponse

from moviepy.video.io.VideoFileClip import VideoFileClip
from moviepy.video.VideoClip import ImageClip
from moviepy.video.compositing.CompositeVideoClip import CompositeVideoClip
import moviepy.video.fx.all as vfx  # type: ignore


router = APIRouter(prefix="/video", tags=["Video"])


def download_file_to_temp(url: str, suffix: str) -> str:
    """Scarica un file da URL in un file temporaneo e ritorna il path."""
    try:
        with requests.get(url, stream=True, timeout=30) as r:
            r.raise_for_status()
            tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
            with open(tmp.name, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            return tmp.name
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Download failed for {url}: {e}")


@router.get("/add-logo")
def add_logo(
    video_url: str = Query(..., description="Public URL of the video (mp4)"),
    logo_url: str = Query(..., description="Public URL of the PNG logo"),
):
    """
    Sovrappone un logo PNG a un video.
    - Il logo appare dopo 1s con fade-in di 0.5s.
    - Viene ridimensionato al 15% della larghezza del video.
    - Restituisce l'MP4 come StreamingResponse.
    """
    video_path, logo_path = None, None
    clip, final_clip = None, None

    try:
        # 1. Scarica video e logo
        video_path = download_file_to_temp(video_url, ".mp4")
        logo_path = download_file_to_temp(logo_url, ".png")

        # 2. Carica il video
        clip = VideoFileClip(video_path)
        video_duration = clip.duration or 0

        # 3. Calcola tempi e durata logo
        start_s = 1 if video_duration > 1 else 0
        logo_duration = max(0, video_duration - start_s)

        # 4. Crea il logo clip
        logo_clip = (
            ImageClip(logo_path, duration=logo_duration)
            .with_start(start_s)
            .with_effects([
                vfx.FadeIn(0.5),
                vfx.Resize(width=int(clip.w * 0.15)),
            ])
            .set_position(("right", "top"))
            .set_opacity(0.9)
        )

        # 5. Composizione finale
        final_clip = CompositeVideoClip([clip, logo_clip])

        # 6. Scrittura su file temporaneo
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=True) as tmp_out:
            final_clip.write_videofile(
                tmp_out.name,
                codec="libx264",
                audio_codec="aac",
                fps=clip.fps or 24,
                threads=4,
                logger=None,
            )
            tmp_out.seek(0)
            video_bytes = tmp_out.read()

        return StreamingResponse(io.BytesIO(video_bytes), media_type="video/mp4")

    finally:
        # cleanup risorse
        if clip:
            clip.close()
        if final_clip:
            final_clip.close()
        for p in (video_path, logo_path):
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except:
                    pass
