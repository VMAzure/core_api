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
from moviepy.video.fx.FadeIn import FadeIn
from moviepy.video.fx.Resize import Resize

router = APIRouter(prefix="/video", tags=["Video"])

def download_file_to_temp(url: str, suffix: str) -> str:
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
    - Ridimensionato al 15% della larghezza del video.
    - Restituisce l'MP4 come streaming.
    """
    video_path = logo_path = None
    clip = final_clip = None

    try:
        # 1) Download asset
        video_path = download_file_to_temp(video_url, ".mp4")
        logo_path = download_file_to_temp(logo_url, ".png")

        # 2) Video sorgente
        clip = VideoFileClip(video_path)
        start_s = 1.0 if (clip.duration or 0) > 1.0 else 0.0
        logo_duration = max(0.0, (clip.duration or 0.0) - start_s)

        # 3) Logo clip + effetti v2
        logo_clip = (
            ImageClip(logo_path, duration=logo_duration)
            .with_start(start_s)
            .with_effects([
                FadeIn(0.5),
                Resize(width=int(clip.w * 0.15)),
            ])
            .with_position(("right", "top"))
            .with_opacity(0.9)
        )

        # 4) Composito
        final_clip = CompositeVideoClip([clip, logo_clip])

        # 5) Scrittura e streaming
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

        return StreamingResponse(BytesIO(video_bytes), media_type="video/mp4")

    finally:
        # Cleanup
        try:
            if final_clip: final_clip.close()
        except: pass
        try:
            if clip: clip.close()
        except: pass
        for p in (video_path, logo_path):
            if p and os.path.exists(p):
                try: os.remove(p)
                except: pass
