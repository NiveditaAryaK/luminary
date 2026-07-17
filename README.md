# Luminary

Luminary is a multimodal storytelling agent built for the Gemini Live Agent Challenge. It turns a short story brief into a live cinematic experience with generated prose, illustrations, narration, branching choices, saved sessions, and resumable story worlds — and can cut the finished story into a narrated short film and publish it to YouTube.

## What It Does

- Generates a cinematic story title and opening scene from a user prompt
- Streams story beats over WebSockets
- Produces scene illustrations alongside the narrative, kept visually consistent by a per-story style bible and reference images
- Lets the user steer the story with preset choices or custom directions
- Supports live spoken narration: the user tells the story out loud and Luminary detects scene beats and illustrates them as they speak
- Supports narration playback with browser speech and optional Google Cloud Text-to-Speech
- Saves stories to Firestore so users can resume unfinished sessions; live sessions are also persisted server-side so they survive restarts and scale-downs
- Guests can start immediately (anonymous auth); signing in with Google upgrades the guest account in place, so stories created as a guest carry over
- Adds director modes, story memory, and a visual recap strip for continuity
- **Finish story → film**: renders the storyboard into an MP4 with Cloud TTS voice narration, burned-in prose subtitles, title/end cards, Ken Burns motion, and crossfades
- **One-click YouTube publish**: uploads the rendered film to the user's channel with Gemini-written title, description, and tags

## Stack

- Frontend: React, Vite, Firebase Auth, Firestore
- Backend: FastAPI, WebSockets, Pydantic, Loguru
- AI: Google Gemini via `google-genai`
- Voice: browser Web Speech APIs, Google Cloud Text-to-Speech
- Film: ffmpeg (bundled in the Docker image; `winget install Gyan.FFmpeg` locally)
- Publish: YouTube Data API v3 (OAuth, resumable uploads)
- Deploy: Cloud Build trigger on push to `master` → Cloud Run

## Architecture

```text
Browser
  |- React + Vite UI
  |- Firebase Auth (anonymous or Google)
  |- Firestore saved-stories archive
  |- Voice input / live narration / narration playback
  |
  -> FastAPI backend (Cloud Run)
       |- story session orchestration + Firestore session persistence
       |- Gemini title + story + image generation (style bible continuity)
       |- WebSocket story streaming + live narration beat detection
       |- Cloud TTS narration
       |- film_service: ffmpeg render pipeline (background jobs)
       |- youtube_service: OAuth connect + resumable upload (background jobs)
```

## Key Features

- `Director Modes`: cinematic, tender, suspenseful, heartbreaking, chaotic
- `Story Memory`: pins durable facts like relationships, goals, secrets, and artifacts
- `Story So Far`: recap strip of earlier visual beats
- `Saved Stories`: archive and resume flow backed by Firestore
- `Voice UX`: voice input, live narration mode, and narration playback
- `Film Assembly`: title card → each beat with Ken Burns pan/zoom for its narration duration → prose subtitles → crossfades → end card; output MP4 in `backend/renders/`
- `YouTube Publish`: per-user OAuth (youtube.upload scope), Gemini-generated metadata, private upload with progress, returns the video URL

## Project Structure

```text
luminary/
|-- backend/
|   |-- main.py               # FastAPI app, endpoints, WebSocket
|   |-- config.py             # env-driven configuration
|   |-- story_service.py      # session orchestration, turns, narration beats
|   |-- visual_engine.py      # style bible + visually-connected scene images
|   |-- narration_service.py  # Cloud TTS (lazy client)
|   |-- film_service.py       # ffmpeg film render pipeline
|   |-- youtube_service.py    # OAuth + resumable YouTube uploads
|   |-- session_store.py      # Firestore session persistence
|   |-- text_utils.py         # shared choice-markup stripping
|   |-- models.py             # session/state dataclasses
|   |-- schemas.py            # request models
|   |-- requirements.txt
|   `-- .env
|-- frontend/
|   |-- package.json
|   |-- .env.example
|   `-- src/
|       |-- components/       # Landing, Story (film + publish UI)
|       |-- hooks/            # story session, narration, film render, publish
|       |-- lib/              # firebase, saved-story store
|       `-- utils/            # API clients, text helpers
|-- cloudbuild.yaml           # build image -> push -> deploy to Cloud Run
|-- firestore.rules
|-- Dockerfile                # frontend build + backend + ffmpeg
`-- README.md
```

## Required Setup

### 1. Backend env

Create `backend/.env`:

```env
GOOGLE_API_KEY=your_gemini_api_key
PORT=8080
GEMINI_TITLE_MODEL=gemini-2.5-flash
GEMINI_STORY_MODEL=gemini-2.5-flash-image
GEMINI_FALLBACK_MODEL=gemini-2.5-flash
GEMINI_IMAGE_MODEL=gemini-2.5-flash-image
TTS_LANGUAGE_CODE=en-US
TTS_DEFAULT_VOICE=en-US-Standard-F
TTS_MAX_CHARS_PER_REQUEST=1800

# Optional — session persistence (defaults to the runtime project's Firestore)
FIRESTORE_PROJECT=
SESSION_COLLECTION=story_sessions
SESSION_TTL_DAYS=30

# Optional — YouTube publishing (feature hidden until all three are set)
YT_CLIENT_ID=xxxxx.apps.googleusercontent.com
YT_CLIENT_SECRET=GOCSPX-...
YT_REDIRECT_URI=https://YOUR_DOMAIN/api/youtube/oauth/callback
```

Notes:

- `GOOGLE_API_KEY` is required for Gemini.
- On Cloud Run, Cloud TTS and Firestore authenticate with the runtime service account — do **not** set `GOOGLE_APPLICATION_CREDENTIALS` there. Locally, set it to a service-account key only if you want Cloud TTS/Firestore during development.
- Cloud TTS requires the Text-to-Speech API enabled and billing attached to the project.
- Session persistence requires a Firestore database (Native mode) in the runtime project, or `FIRESTORE_PROJECT` pointing at one the service account can access. Without it the app still runs; sessions just live in memory only.

### 2. Frontend env

Copy `frontend/.env.example` to `frontend/.env.local` and fill in your Firebase web app config:

```env
VITE_FIREBASE_API_KEY=...
VITE_FIREBASE_AUTH_DOMAIN=...
VITE_FIREBASE_PROJECT_ID=...
VITE_FIREBASE_STORAGE_BUCKET=...
VITE_FIREBASE_MESSAGING_SENDER_ID=...
VITE_FIREBASE_APP_ID=...
VITE_FIREBASE_MEASUREMENT_ID=...
```

Vite inlines these at build time, so for deployed builds they must reach the Docker build as build args — see [Deployment](#deployment).

### 3. Firebase setup

In Firebase console:

- enable `Authentication`
  - `Anonymous`
  - `Google`
- create `Cloud Firestore`
- publish the rules from [`firestore.rules`](firestore.rules)

### 4. Film rendering

- ffmpeg must be on PATH. The Dockerfile installs it (plus DejaVu fonts for burned-in text); locally: `winget install Gyan.FFmpeg` (Windows) or your package manager.
- Films render as background jobs; on Cloud Run set **CPU always allocated** and at least **1 GiB memory** so renders are not throttled between status polls.

### 5. YouTube publishing (optional)

In the Google Cloud project:

1. Enable **YouTube Data API v3**.
2. Configure the **OAuth consent screen** (External, Testing) and add each publisher's Google account under **Test users**.
3. Create an **OAuth client ID** (Web application) with authorized redirect URI `https://YOUR_DOMAIN/api/youtube/oauth/callback`.
4. Set `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, and `YT_REDIRECT_URI` on the backend.

Constraints while the OAuth app is unverified: only approved test users can connect, uploads are forced **private**, and the default API quota allows roughly six uploads per day. The UI copy reflects this ("Published to your channel (private)").

## Local Development

### Backend

```powershell
cd backend
py -3.13 -m pip install -r requirements.txt
py -3.13 main.py
```

Backend runs on `http://127.0.0.1:8080`.

### Frontend

```powershell
cd frontend
npm.cmd install
npm.cmd run dev
```

Frontend runs on `http://localhost:5173`.

In development, the frontend talks to:

- HTTP API through Vite proxy
- WebSocket story stream directly at `ws://127.0.0.1:8080/ws/{session_id}`

## API Overview

All routes are also available under an `/api` prefix (used by the frontend).

### Stories

- `POST /story/create` — start a new story session (`genre`, `premise`, `director_mode`)
- `POST /story/restore` — rebuild a session from a saved snapshot
- `GET /story/{session_id}` — current session snapshot
- `WS /ws/{session_id}` — streams story text, images, choices, director mode, memory, and storyboard updates; accepts choices and live narration chunks

### Narration

- `GET /narration/voices` — available Cloud TTS voices
- `POST /narration/speak` — synthesize narrated audio for a story beat

### Film

- `POST /story/{sid}/film` — start a film render (background job)
- `GET /story/{sid}/film/status` — job status, progress, and stage message
- `GET /story/{sid}/film/download` — the rendered MP4

### YouTube

- `GET /youtube/status?uid=` — `{configured, connected}` for this user
- `GET /youtube/auth/start?uid=` — redirects to Google consent (youtube.upload scope)
- `GET /youtube/oauth/callback` — OAuth redirect target; stores tokens per user
- `POST /story/{sid}/publish` — upload the rendered film (background job)
- `GET /story/{sid}/publish/status` — upload progress and final video URL

### Health

- `GET /health` — includes `session_persistence` status for quick diagnosis

## Deployment

Pushing to `master` triggers Cloud Build (`cloudbuild.yaml`): the Docker image is built (frontend compiled inside the image, ffmpeg installed), pushed to Artifact Registry, and deployed to Cloud Run.

The Firebase web config is baked into the frontend bundle at build time, so the Cloud Build **trigger** must define these substitution variables (Cloud Build → Triggers → edit → Substitution variables), mirroring `frontend/.env.local`:

```text
_VITE_FIREBASE_API_KEY
_VITE_FIREBASE_AUTH_DOMAIN
_VITE_FIREBASE_PROJECT_ID
_VITE_FIREBASE_STORAGE_BUCKET
_VITE_FIREBASE_MESSAGING_SENDER_ID
_VITE_FIREBASE_APP_ID
_VITE_FIREBASE_MEASUREMENT_ID
```

If they are missing, the build still succeeds but the deployed app runs without Firebase — no sign-in and no saved-stories archive.

Cloud Run service checklist:

- CPU **always allocated**, memory **1 GiB+**, max instances 1 (sessions are cached per instance)
- Text-to-Speech API enabled on the project (voice narration in films)
- Firestore database created (session persistence, YouTube tokens)
- `YT_*` env vars set if YouTube publishing is enabled

## Notes

- Live sessions are cached in memory and persisted to Firestore after every turn; any instance can lazily rehydrate a session after a deploy or scale-down.
- Rendered films are written to instance-local disk (`backend/renders/`) — publish to YouTube or download promptly; a new instance cannot serve an old instance's file.
- Cloud TTS has a frontend-side usage guardrail and falls back to browser narration automatically.
- The frontend bundle is large because Firebase and narration logic are bundled together.

## Troubleshooting

- `Live story connection failed`
  - make sure the backend is running on `127.0.0.1:8080`
  - restart frontend after websocket-related changes

- `Session not found`
  - the in-memory session is gone and Firestore persistence is not configured (check `GET /health` → `session_persistence`)

- Saved stories missing
  - confirm Firebase Auth providers are enabled
  - confirm Firestore rules are published
  - confirm you are signed in with the same Firebase user
  - note: signing in with Google normally upgrades the guest account (stories carry over), but if that Google account already has its own Luminary user, the app switches to it and shows that account's archive instead

- No voice in rendered films / no Cloud narration
  - check `GET /api/narration/voices` — the error message states the cause
  - verify billing is enabled and the Text-to-Speech API is turned on
  - on Cloud Run, remove any stale `GOOGLE_APPLICATION_CREDENTIALS` env var

- YouTube connect fails
  - the OAuth callback popup shows the underlying error
  - `Error 403: access_denied` → add the Google account under OAuth consent screen **Test users**
  - verify `YT_REDIRECT_URI` matches the OAuth client's authorized redirect URI exactly

- Text appears but no image
  - the backend has a fallback image generation pass, but model access/quota can still force text-only output
