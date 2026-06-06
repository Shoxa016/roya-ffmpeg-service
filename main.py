import os
import uuid
import subprocess
import requests
import tempfile
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional

app = FastAPI(title="Roya FFmpeg Service")

API_KEY = os.environ.get("API_KEY", "roya-secret-key")


class StitchRequest(BaseModel):
    api_key: str
    clip_urls: list[str]          # list of video URLs to stitch in order
    hook_text: Optional[str] = None
    body_text: Optional[str] = None
    challenge_text: Optional[str] = None
    hashtag_text: Optional[str] = None
    output_format: str = "mp4"


class StitchResponse(BaseModel):
    success: bool
    message: str
    download_url: Optional[str] = None


def download_file(url: str, dest_path: str) -> bool:
    """Download a file from URL to local path."""
    try:
        r = requests.get(url, timeout=60, stream=True)
        r.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
    except Exception as e:
        print(f"Download failed for {url}: {e}")
        return False


def add_text_overlay(input_path: str, output_path: str, text: str,
                      y_pos: str, font_size: int = 48, duration: float = None,
                      start_time: float = 0) -> bool:
    """Add text overlay to a video using FFmpeg drawtext filter."""
    # Clean text for FFmpeg (escape special chars)
    safe_text = text.replace("'", "\\'").replace(":", "\\:").replace("\\", "\\\\")

    duration_filter = ""
    if duration:
        duration_filter = f":enable='between(t,{start_time},{start_time+duration})'"

    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-vf",
        f"drawtext=text='{safe_text}':fontcolor=white:fontsize={font_size}:x=(w-text_w)/2:y={y_pos}:box=1:boxcolor=black@0.5:boxborderw=10{duration_filter}",
        "-codec:a", "copy",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0


@app.get("/")
def root():
    return {"status": "Roya FFmpeg Service running", "version": "1.0"}


@app.get("/health")
def health():
    # Check FFmpeg is available
    result = subprocess.run(["ffmpeg", "-version"], capture_output=True)
    ffmpeg_ok = result.returncode == 0
    return {"status": "ok", "ffmpeg": ffmpeg_ok}


@app.post("/stitch")
def stitch_videos(req: StitchRequest):
    """
    Main endpoint: stitch multiple video clips together + add text overlays.
    Returns a download URL for the finished video.
    """
    # Auth check
    if req.api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

    if not req.clip_urls:
        raise HTTPException(status_code=400, detail="No clip URLs provided")

    job_id = str(uuid.uuid4())[:8]
    work_dir = f"/tmp/roya_{job_id}"
    os.makedirs(work_dir, exist_ok=True)

    try:
        # 1. Download all clips
        clip_paths = []
        for i, url in enumerate(req.clip_urls):
            dest = f"{work_dir}/clip_{i}.mp4"
            print(f"Downloading clip {i}: {url}")
            if not download_file(url, dest):
                raise HTTPException(status_code=400, detail=f"Failed to download clip {i}: {url}")
            clip_paths.append(dest)

        # 2. Create concat list file
        concat_file = f"{work_dir}/concat.txt"
        with open(concat_file, "w") as f:
            for p in clip_paths:
                f.write(f"file '{p}'\n")

        # 3. Concatenate clips
        stitched = f"{work_dir}/stitched.mp4"
        concat_cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", concat_file,
            "-c", "copy",
            stitched
        ]
        result = subprocess.run(concat_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Concat error: {result.stderr}")
            raise HTTPException(status_code=500, detail=f"FFmpeg concat failed: {result.stderr[-500:]}")

        # 4. Add text overlays if provided
        current_input = stitched
        overlay_step = 0

        # Calculate timing based on clip count
        # Assume each clip is ~8 seconds
        clip_duration = 8.0

        if req.hook_text:
            overlay_out = f"{work_dir}/overlay_{overlay_step}.mp4"
            add_text_overlay(
                current_input, overlay_out,
                text=req.hook_text,
                y_pos="h*0.15",
                font_size=52,
                duration=clip_duration,
                start_time=0
            )
            current_input = overlay_out
            overlay_step += 1

        if req.body_text:
            overlay_out = f"{work_dir}/overlay_{overlay_step}.mp4"
            add_text_overlay(
                current_input, overlay_out,
                text=req.body_text,
                y_pos="h*0.75",
                font_size=40,
                duration=clip_duration * 2,
                start_time=clip_duration
            )
            current_input = overlay_out
            overlay_step += 1

        if req.challenge_text:
            overlay_out = f"{work_dir}/overlay_{overlay_step}.mp4"
            add_text_overlay(
                current_input, overlay_out,
                text=req.challenge_text,
                y_pos="h*0.80",
                font_size=38,
                duration=clip_duration,
                start_time=clip_duration * 3
            )
            current_input = overlay_out
            overlay_step += 1

        # 5. Final output — ensure 9:16 vertical format + proper encoding for YouTube
        final_output = f"/tmp/roya_output_{job_id}.mp4"
        encode_cmd = [
            "ffmpeg", "-y", "-i", current_input,
            "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            final_output
        ]
        result = subprocess.run(encode_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Encode error: {result.stderr}")
            raise HTTPException(status_code=500, detail=f"FFmpeg encode failed: {result.stderr[-500:]}")

        # 6. Clean up work dir
        import shutil
        shutil.rmtree(work_dir, ignore_errors=True)

        return {
            "success": True,
            "job_id": job_id,
            "message": "Video stitched successfully",
            "download_url": f"/download/{job_id}"
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/download/{job_id}")
def download_video(job_id: str, api_key: str):
    """Download the stitched video file."""
    if api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

    path = f"/tmp/roya_output_{job_id}.mp4"
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Video not found or expired")

    return FileResponse(
        path,
        media_type="video/mp4",
        filename=f"roya_video_{job_id}.mp4"
    )


@app.post("/stitch-single")
def stitch_single_with_overlay(req: StitchRequest):
    """
    Simplified endpoint: takes ONE background video URL + adds text overlays.
    Useful when you already have a Pexels/Veo video and just need text.
    """
    if req.api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

    if not req.clip_urls:
        raise HTTPException(status_code=400, detail="No clip URL provided")

    job_id = str(uuid.uuid4())[:8]
    work_dir = f"/tmp/roya_{job_id}"
    os.makedirs(work_dir, exist_ok=True)

    try:
        # Download single video
        src = f"{work_dir}/source.mp4"
        if not download_file(req.clip_urls[0], src):
            raise HTTPException(status_code=400, detail="Failed to download video")

        current_input = src

        # Build a single complex filtergraph with all text at once
        filters = []
        if req.hook_text:
            safe = req.hook_text.replace("'", "\\'").replace(":", "\\:")
            filters.append(
                f"drawtext=text='{safe}':fontcolor=white:fontsize=52:x=(w-text_w)/2:y=h*0.12:box=1:boxcolor=black@0.6:boxborderw=12:enable='between(t,0,10)'"
            )
        if req.body_text:
            safe = req.body_text.replace("'", "\\'").replace(":", "\\:")
            filters.append(
                f"drawtext=text='{safe}':fontcolor=white:fontsize=38:x=(w-text_w)/2:y=h*0.72:box=1:boxcolor=black@0.6:boxborderw=10:enable='between(t,10,25)'"
            )
        if req.challenge_text:
            safe = req.challenge_text.replace("'", "\\'").replace(":", "\\:")
            filters.append(
                f"drawtext=text='{safe}':fontcolor=yellow:fontsize=38:x=(w-text_w)/2:y=h*0.78:box=1:boxcolor=black@0.6:boxborderw=10:enable='between(t,25,32)'"
            )
        if req.hashtag_text:
            safe = req.hashtag_text.replace("'", "\\'").replace(":", "\\:")
            filters.append(
                f"drawtext=text='{safe}':fontcolor=white:fontsize=30:x=(w-text_w)/2:y=h*0.88:box=1:boxcolor=black@0.4:boxborderw=8:enable='between(t,25,32)'"
            )

        vf = ",".join(filters) if filters else "null"

        final_output = f"/tmp/roya_output_{job_id}.mp4"
        cmd = [
            "ffmpeg", "-y", "-i", current_input,
            "-vf", f"scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2[scaled];[scaled]{vf}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            final_output
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            # Fallback: try without complex filter
            simple_cmd = [
                "ffmpeg", "-y", "-i", current_input,
                "-vf", vf,
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart",
                final_output
            ]
            result2 = subprocess.run(simple_cmd, capture_output=True, text=True)
            if result2.returncode != 0:
                raise HTTPException(status_code=500, detail=f"FFmpeg failed: {result2.stderr[-500:]}")

        import shutil
        shutil.rmtree(work_dir, ignore_errors=True)

        return {
            "success": True,
            "job_id": job_id,
            "message": "Video processed successfully",
            "download_url": f"/download/{job_id}"
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
