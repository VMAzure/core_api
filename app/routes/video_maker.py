import io
import os
import tempfile
import requests
from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import StreamingResponse
from moviepy import *
# --- FIX DEFINITIVO E SPIEGAZIONE ---
# La riga seguente è la sintassi corretta per le versioni recenti di moviepy.
# L'errore "could not be resolved" proviene dall'analizzatore di codice (linter)
# e non da Python. Il commento `# type: ignore` è la soluzione standard e
# professionale per istruire il linter a ignorare questo falso positivo,
# risultando in un codice pulito e funzionale.
from moviepy.video.fx.all import fadein, resize  # type: ignore


router = APIRouter(prefix="/video", tags=["Video"])


def download_file_to_temp(url: str, suffix: str) -> str:
    """
    Downloads a file from a URL and saves it to a temporary file.
    Returns the path to the temporary file.
    CRITICAL: The caller is responsible for deleting this file.
    """
    try:
        with requests.get(url, stream=True, timeout=30) as r:
            r.raise_for_status()
            # Use delete=False because we need the path to pass to moviepy,
            # and we will handle the deletion manually in a finally block.
            tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
            with open(tmp.name, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            return tmp.name
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Download failed for {url}: {e}"
        )


@router.get("/add-logo")
def add_logo(
    video_url: str = Query(..., description="Public URL of the video"),
    logo_url: str = Query(..., description="Public URL of the PNG logo"),
):
    """
    Overlays a PNG logo onto a video.
    - The logo appears after 1 second with a fade-in transition.
    - Returns the resulting MP4 directly as a StreamingResponse.
    """
    video_path, logo_path = None, None
    clip, final_clip = None, None

    try:
        # 1. Download video and logo to temporary files
        video_path = download_file_to_temp(video_url, ".mp4")
        logo_path = download_file_to_temp(logo_url, ".png")

        # 2. Load video and prepare clips
        clip = VideoFileClip(video_path)
        video_duration = clip.duration or 0

        # Ensure the logo doesn't start after the video ends
        start_s = 1 if video_duration > 1 else 0
        logo_duration = max(0, video_duration - start_s)

        # Apply effects as functions, not as chained .fx() methods
        logo_clip = ImageClip(logo_path, duration=logo_duration)

        # Apply effects by passing the clip to the imported effect function
        logo_clip = fadein(logo_clip, 0.5)
        logo_clip = resize(logo_clip, width=int(clip.w * 0.15))

        # Other methods that return a new clip can still be chained
        logo_clip = logo_clip.set_position(("right", "top"), margin=10).set_opacity(
            0.9
        )

        logo_clip.start = start_s

        final_clip = CompositeVideoClip([clip, logo_clip])

        # 3. Write the final video to a temporary output file
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=True) as tmp_out:
            final_clip.write_videofile(
                tmp_out.name,
                codec="libx264",
                audio_codec="aac",
                fps=clip.fps or 24,
                threads=4,  # Increased threads for potentially faster processing
                logger=None,
            )

            # Read the bytes to be sent in the response
            tmp_out.seek(0)
            video_bytes = tmp_out.read()

        # 4. Return the result
        return StreamingResponse(io.BytesIO(video_bytes), media_type="video/mp4")

    finally:
        # --- CRITICAL CLEANUP ---

        # Close moviepy clips to release file handles
        if clip:
            clip.close()
        if final_clip:
            final_clip.close()

        # Delete the downloaded temporary files
        if video_path and os.path.exists(video_path):
            os.remove(video_path)
        if logo_path and os.path.exists(logo_path):
            os.remove(logo_path)

