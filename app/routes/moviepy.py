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
