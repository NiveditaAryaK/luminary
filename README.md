# Luminary

Luminary is a multimodal storytelling agent built for the Gemini Live Agent Challenge. It turns a short story brief into a live cinematic experience with generated prose, illustrations, narration, branching choices, saved sessions, and resumable story worlds.

## What It Does

- Generates a cinematic story title and opening scene from a user prompt
- Streams story beats over WebSockets
- Produces scene illustrations alongside the narrative
- Lets the user steer the story with preset choices or custom directions
- Supports voice input for prompts and story directions
- Supports narration playback with browser speech and optional Google Cloud Text-to-Speech
- Saves stories to Firestore so users can resume unfinished sessions
- Adds director modes, story memory, and a visual recap strip for continuity

## Stack

- Frontend: React, Vite, Firebase Auth, Firestore
- Backend: FastAPI, WebSockets, Pydantic, Loguru
- AI: Google Gemini via `google-genai`, Google ADK
- Voice: browser Web Speech APIs, optional Google Cloud Text-to-Speech

## Architecture

```text
Browser
  |- React + Vite UI
  |- Firebase Auth
  |- Firestore saved stories
  |- Voice input / narration playback
  |
  -> FastAPI backend
       |- story session orchestration
       |- Gemini title + story + image generation
       |- WebSocket story streaming
       |- story restore/snapshot endpoints
       |- optional Cloud TTS narration
```

## Key Features

- `Director Modes`: cinematic, tender, suspenseful, heartbreaking, chaotic
- `Story Memory`: pins durable facts like relationships, goals, secrets, and artifacts
- `Story So Far`: recap strip of earlier visual beats
- `Saved Stories`: archive and resume flow backed by Firestore
- `Voice UX`: voice input plus narration playback

## Project Structure

```text
luminary/
|-- backend/
|   |-- main.py
|   |-- config.py
|   |-- story_service.py
|   |-- narration_service.py
|   |-- models.py
|   |-- schemas.py
|   |-- requirements.txt
|   `-- .env
|-- frontend/
|   |-- package.json
|   |-- .env.example
|   `-- src/
|       |-- components/
|       |-- hooks/
|       |-- lib/
|       `-- utils/
|-- firestore.rules
`-- Dockerfile
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
GOOGLE_APPLICATION_CREDENTIALS=C:\path\to\service-account.json
```

Notes:

- `GOOGLE_API_KEY` is required for Gemini.
- `GOOGLE_APPLICATION_CREDENTIALS` is only needed if you want Cloud TTS narration.
- Cloud TTS also requires the Text-to-Speech API enabled and billing attached to the Google Cloud project.

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

### 3. Firebase setup

In Firebase console:

- enable `Authentication`
  - `Anonymous`
  - `Google`
- create `Cloud Firestore`
- publish the rules from [`firestore.rules`](/c:/Users/Nived/OneDrive/Desktop/luminary/firestore.rules)

## Local Development

### Backend

```powershell
cd backend
py -3.13 -m pip install -r requirements.txt
..\env\Scripts\python.exe main.py
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

### `POST /story/create`

Starts a new story session.

Request:

```json
{
  "genre": "fantasy",
  "premise": "An astronomer discovers a staircase hidden inside moonlight.",
  "director_mode": "cinematic"
}
```

### `POST /story/restore`

Restores a saved story session from persisted history.

### `GET /story/{session_id}`

Returns the current in-memory session snapshot.

### `GET /narration/voices`

Lists available Cloud TTS voices when configured.

### `POST /narration/speak`

Synthesizes narrated audio for a story beat.

### `WS /ws/{session_id}`

Streams:

- story text
- image payloads
- choices
- director mode updates
- story memory updates
- storyboard recap updates

## Notes

- Story sessions are in-memory on the backend, so restarting the backend clears active runtime sessions.
- Firestore keeps the user-facing saved archive, but restore still depends on backend restore endpoints.
- Cloud TTS has a frontend-side usage guardrail and can fall back to browser narration automatically.
- The frontend bundle is currently large because Firebase and narration logic are bundled together.

## Docker

The repo includes a Dockerfile, but local split frontend/backend development is the easiest path while iterating.

If you package for deployment, make sure the container or runtime has:

- backend env vars
- Gemini API access
- optional Google service account credentials for Cloud TTS

## Troubleshooting

- `Live story connection failed`
  - make sure the backend is running on `127.0.0.1:8080`
  - restart frontend after websocket-related changes

- Saved stories missing
  - confirm Firebase Auth providers are enabled
  - confirm Firestore rules are published
  - confirm you are signed in with the same Firebase user

- No Cloud narration
  - verify billing is enabled
  - enable Cloud Text-to-Speech API
  - set `GOOGLE_APPLICATION_CREDENTIALS`

- Text appears but no image
  - the backend has a fallback image generation pass, but model access/quota can still force text-only output

## Commit Message

`fix: stabilize live story flow and refresh the README for current architecture`
