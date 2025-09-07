from pydantic import BaseModel, HttpUrl, validator
from typing import List, Optional

class VideoSegment(BaseModel):
    url: HttpUrl
    text1: Optional[str] = None
    text2: Optional[str] = None

class VideoEditRequest(BaseModel):
    video_segments: List[VideoSegment]
    logo_url: Optional[HttpUrl] = None
    text_logo: Optional[str] = None

    @validator("video_segments")
    def validate_segments(cls, v):
        if not (1 <= len(v) <= 5):
            raise ValueError("You must provide between 1 and 5 video segments.")
        return v


import io
import os
import tempfile
import requests
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from typing import List
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from moviepy import CompositeVideoClip, ImageClip, VideoFileClip
from moviepy.video.fx.CrossFadeIn import CrossFadeIn
from moviepy.video.fx.FadeIn import FadeIn
from moviepy.video.fx.FadeOut import FadeOut
from moviepy.video.fx.Resize import Resize

router = APIRouter(prefix="/video", tags=["Video"])

MAX_DURATION = 25.0
XFADE_SEC = 0.4
FINAL_BLACK_SEC = 3.0

def download_temp_file(url: str, suffix: str) -> str:
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    tf = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tf.write(r.content)
    tf.flush()
    return tf.name

def create_text_clip(text: str, duration: float, size: tuple, position: tuple) -> ImageClip:
    W, H = size
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype("DejaVuSans-Bold.ttf", 50)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x, y = position
    draw.text((x - tw // 2, y - th // 2), text, font=font, fill=(255, 255, 255, 255), stroke_width=3, stroke_fill="black")
    np_img = np.array(img)
    return ImageClip(np_img, duration=duration)

@router.post("/add-logo")
def add_logo(request: VideoEditRequest):
    temp_files = []
    clips = []
    overlays = []

    try:
        total = 0.0

        for i, segment in enumerate(request.video_segments):
            path = download_temp_file(str(segment.url), ".mp4")
            temp_files.append(path)
            clip = VideoFileClip(path)
            remaining = MAX_DURATION - total
            if remaining <= 0:
                break
            clip_duration = min(clip.duration, remaining + (XFADE_SEC if i > 0 else 0))
            trimmed = clip.subclipped(0, clip_duration)

            if i > 0:
                trimmed = trimmed.with_start(total - XFADE_SEC).with_effects([CrossFadeIn(XFADE_SEC)])
            else:
                trimmed = trimmed.with_start(0)

            clips.append(trimmed)

            # TEXT overlay
            text_start = trimmed.start + 0.5
            text_dur = max(0.0, trimmed.duration - 1.0)
            if segment.text1:
                overlays.append(
                    create_text_clip(segment.text1, text_dur, trimmed.size, (trimmed.w // 2, int(trimmed.h * 0.3)))
                    .with_start(text_start)
                    .with_effects([FadeIn(0.4), FadeOut(0.4)])
                )
            if segment.text2:
                overlays.append(
                    create_text_clip(segment.text2, text_dur, trimmed.size, (trimmed.w // 2, int(trimmed.h * 0.45)))
                    .with_start(text_start)
                    .with_effects([FadeIn(0.4), FadeOut(0.4)])
                )

            total = trimmed.end

        base = CompositeVideoClip(clips + overlays).with_duration(min(total, MAX_DURATION))

        # LOGO overlay ultimi 3 secondi
        if request.logo_url:
            logo_path = download_temp_file(str(request.logo_url), ".png")
            temp_files.append(logo_path)
            start_logo = max(0.0, base.duration - 3.0)
            logo_duration = base.duration - start_logo
            logo_clip = (
                ImageClip(logo_path, duration=logo_duration)
                .with_start(start_logo)
                .with_effects([
                    FadeIn(0.5),
                    Resize(width=int(base.w * 0.9)),
                ])
                .with_position("center")
                .with_opacity(0.95)
            )
            base = CompositeVideoClip([base, logo_clip], size=base.size)

        # FRAME finale nero con logo e testo
        if request.logo_url or request.text_logo:
            black_frame = Image.new("RGB", (base.w, base.h), (0, 0, 0))
            black_np = np.array(black_frame)
            black_clip = ImageClip(black_np, duration=FINAL_BLACK_SEC).with_start(base.duration)

            final_overlays = []
            if request.logo_url:
                final_overlays.append(
                    ImageClip(logo_path, duration=FINAL_BLACK_SEC)
                    .with_start(base.duration)
                    .with_effects([Resize(width=int(base.w * 0.5))])
                    .with_position(("center", int(base.h * 0.35)))
                    .with_opacity(1.0)
                )
            if request.text_logo:
                final_overlays.append(
                    create_text_clip(request.text_logo, FINAL_BLACK_SEC, (base.w, base.h), (base.w // 2, int(base.h * 0.75)))
                    .with_start(base.duration)
                )

            final = CompositeVideoClip([base, black_clip, *final_overlays], size=base.size).with_duration(base.duration + FINAL_BLACK_SEC)
        else:
            final = base

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
            return StreamingResponse(io.BytesIO(tmp.read()), media_type="video/mp4")

    finally:
        for f in temp_files:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except:
                    pass
        for clip in clips:
            try:
                clip.close()
            except:
                pass
        try:
            base.close()
        except:
            pass
        try:
            final.close()
        except:
            pass
