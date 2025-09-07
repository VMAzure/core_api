from pydantic import BaseModel, HttpUrl, validator
from typing import List, Optional

class VideoEditRequest(BaseModel):
    video_urls: List[HttpUrl]
    logo_url: Optional[HttpUrl] = None

    @validator("video_urls")
    def check_video_count(cls, v):
        if not (1 <= len(v) <= 5):
            raise ValueError("You must provide between 1 and 5 video URLs.")
        return v


from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from moviepy.video.io.VideoFileClip import VideoFileClip
from moviepy.video.VideoClip import ImageClip
from moviepy.video.compositing.CompositeVideoClip import CompositeVideoClip
from moviepy.video.fx.FadeIn import FadeIn
from moviepy.video.fx.Resize import Resize
from moviepy.video.fx.CrossFadeIn import CrossFadeIn
import tempfile, requests, os, io
from io import BytesIO

router = APIRouter(prefix="/video", tags=["Video"])

MAX_DURATION = 25.0  # seconds
XFADE_SEC = 0.4      # crossfade duration

def download_temp_file(url: str, suffix: str) -> str:
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp.write(r.content)
    tmp.flush()
    return tmp.name

@router.post("/add-logo")
def add_logo(request: VideoEditRequest):
    temp_files = []
    clips = []

    try:
        # 1. Scarica i video
        for url in request.video_urls:
            path = download_temp_file(str(url), ".mp4")
            temp_files.append(path)
            clips.append(VideoFileClip(path))

        # 2. Applica trim e transizioni fino a 25s
        assembled = []
        total = 0.0

        for i, clip in enumerate(clips):
            remaining = MAX_DURATION - total
            if remaining <= 0:
                break

            # durata clip = intera se c'è spazio, altrimenti taglia
            dur = min(clip.duration, remaining + (XFADE_SEC if i > 0 else 0))
            trimmed = clip.subclipped(0, dur)

            if i > 0:
                # crossfade: la nuova clip inizia XFADE_SEC prima della fine della precedente
                trimmed = trimmed.with_start(total - XFADE_SEC).with_effects([
                    CrossFadeIn(XFADE_SEC)
                ])
            else:
                trimmed = trimmed.with_start(0)

            assembled.append(trimmed)
            total = trimmed.end


        if not assembled:
            raise HTTPException(400, "Total video duration is zero.")

        base = CompositeVideoClip(assembled).with_duration(min(total, MAX_DURATION))

        # 3. Se c'è logo, aggiungilo
        if request.logo_url:
            logo_path = download_temp_file(str(request.logo_url), ".png")
            temp_files.append(logo_path)

            start_logo = max(0.0, base.duration - 3.0)
            logo_duration = base.duration - start_logo

            logo = (
                ImageClip(logo_path, duration=logo_duration)
                .with_start(start_logo)
                .with_effects([
                    FadeIn(0.5),
                    Resize(width=int(base.w * 0.9))  # ✅ v2 resize con max 90% larghezza
                ])
                .with_position("center")
                .with_opacity(0.95)
            )
            final = CompositeVideoClip([base, logo], size=base.size)
        else:
            final = base


        # 4. Scrivi il risultato in buffer
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=True) as tmp:
            final.write_videofile(
                tmp.name,
                codec="libx264",
                audio_codec="aac",
                fps=base.fps or 24,
                threads=4,
                logger=None,
            )
            tmp.seek(0)
            return StreamingResponse(BytesIO(tmp.read()), media_type="video/mp4")

    finally:
        for path in temp_files:
            if os.path.exists(path):
                os.remove(path)
        for clip in clips:
            try: clip.close()
            except: pass
        try: base.close()
        except: pass
        try: final.close()
        except: pass
