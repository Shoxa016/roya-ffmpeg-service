# Roya FFmpeg Microservice

A lightweight video stitching API for the Roya Rewires n8n workflow.
Runs on Render.com free tier with FFmpeg built in.

---

## Deploy to Render.com (step by step)

### Step 1 — Push to GitHub
1. Create a new GitHub repo called `roya-ffmpeg-service`
2. Upload all 4 files: `main.py`, `requirements.txt`, `Dockerfile`, `render.yaml`

### Step 2 — Connect to Render.com
1. Go to https://render.com and sign in
2. Click **New → Web Service**
3. Connect your GitHub repo `roya-ffmpeg-service`
4. Render will auto-detect the Dockerfile

### Step 3 — Set environment variable
In Render dashboard → Environment:
- Key: `API_KEY`
- Value: choose a strong secret (e.g. `roya-secret-2024`)

### Step 4 — Deploy
Click **Deploy**. Wait ~3 minutes for first build (FFmpeg install takes time).

Your service URL will be: `https://roya-ffmpeg-service.onrender.com`

---

## API Endpoints

### GET /health
Check if service + FFmpeg are running.
```
curl https://roya-ffmpeg-service.onrender.com/health
```

### POST /stitch
Stitch multiple clips together + add text overlays.
```json
{
  "api_key": "roya-secret-2024",
  "clip_urls": [
    "https://veo-clip-1.mp4",
    "https://veo-clip-2.mp4",
    "https://veo-clip-3.mp4"
  ],
  "hook_text": "Your brain is lying to you",
  "body_text": "Studies show that 80% of thoughts are recycled",
  "challenge_text": "Try this tonight: write 3 thoughts you want to rewire",
  "hashtag_text": "#BrainHack #RewireYourBrain"
}
```

### POST /stitch-single
Add text overlays to a single background video (use with Pexels/Veo).
```json
{
  "api_key": "roya-secret-2024",
  "clip_urls": ["https://pexels-video-url.mp4"],
  "hook_text": "Your brain is lying to you",
  "body_text": "Here is why...",
  "challenge_text": "Try this tonight",
  "hashtag_text": "#BrainHack"
}
```

### GET /download/{job_id}?api_key=...
Download the processed video.

---

## n8n Integration

Add an HTTP Request node after your AI Agent:

**Method:** POST  
**URL:** `https://roya-ffmpeg-service.onrender.com/stitch-single`  
**Body (JSON):**
```json
{
  "api_key": "roya-secret-2024",
  "clip_urls": ["{{ $('HTTP Request2').item.json.videos[0].video_files[0].link }}"],
  "hook_text": "{{ JSON.parse($('AI Agent').item.json.output).hook }}",
  "body_text": "{{ JSON.parse($('AI Agent').item.json.output).body }}",
  "challenge_text": "{{ JSON.parse($('AI Agent').item.json.output).challenge }}",
  "hashtag_text": "{{ JSON.parse($('AI Agent').item.json.output).tiktok_hashtags }}"
}
```

Then use the `download_url` from the response to fetch the final video.

---

## Note on Render Free Tier
- Free services spin down after 15 min of inactivity
- First request after spin-down takes ~30 seconds (cold start)
- Add a Wait node (45s) in n8n before calling this service if needed
- 750 free hours/month = plenty for daily videos
