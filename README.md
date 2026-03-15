# Luminary

Luminary is an AI-powered cinematic storytelling app that lets users create interactive stories with branching choices and generated illustrations.

The project combines:

- A `React + Vite` frontend for story setup and playback
- A `FastAPI` backend for session management and real-time story generation
- Google Gemini models for title generation, narrative beats, and multimodal image output

## Features

- Start a story from a custom premise
- Pick from multiple genres including fantasy, sci-fi, mystery, horror, romance, adventure, and historical
- Receive streamed story beats over WebSockets
- Generate scene illustrations alongside story text
- Continue the narrative through player choices
- Run locally in split frontend/backend mode or as a single Dockerized app

## Project Structure

```text
luminary/
|-- backend/
|   |-- main.py
|   |-- agent.py
|   |-- story_engine.py
|   `-- requirements.txt
|-- frontend/
|   |-- package.json
|   |-- vite.config.js
|   `-- src/
`-- Dockerfile
```

## Tech Stack

- Frontend: React 18, Vite
- Backend: FastAPI, Uvicorn, WebSockets, Pydantic
- AI: `google-genai`, `google-adk`
- Runtime: Node.js 20+, Python 3.12+

## Environment Variables

Create a `.env` file in `backend/` with:

```env
GOOGLE_API_KEY=your_google_api_key_here
PORT=8080
```

Notes:

- `GOOGLE_API_KEY` is required for Gemini requests.
- `PORT` is optional locally and defaults to `8080`.

## Local Development

### 1. Start the backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

The backend will start on `http://localhost:8080`.

### 2. Start the frontend

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

The frontend will start on `http://localhost:5173`.

## Docker

Build and run the full app:

```bash
docker build -t luminary .
docker run --env GOOGLE_API_KEY=your_google_api_key_here -p 8080:8080 luminary
```

This builds the frontend, copies the production bundle into the backend, and serves everything from the FastAPI app on `http://localhost:8080`.

## How It Works

### Story creation

`POST /story/create`

Request body:

```json
{
  "genre": "fantasy",
  "premise": "A cartographer discovers a city that appears only during eclipses."
}
```

Response:

```json
{
  "session_id": "generated-session-id",
  "title": "The City Beneath the Shadow",
  "genre": "fantasy"
}
```

### Real-time story streaming

After a session is created, the client connects to:

```text
ws://localhost:8080/ws/{session_id}
```

The websocket sends and receives JSON messages for:

- connection status
- story text
- generated images
- completion state
- user choices

## Backend Overview

### `backend/main.py`

- Loads environment variables
- Initializes the Gemini client
- Creates story sessions
- Streams story beats and images over WebSockets
- Serves static frontend assets when a production build exists

### `backend/story_engine.py`

- Contains the reusable story engine
- Defines genres, session state, and story segments
- Handles multimodal generation and fallback logic

### `backend/agent.py`

- Defines a Google ADK agent wrapper around the storytelling engine
- Exposes helper tools for starting and continuing sessions

## Development Notes

- The backend stores story sessions in memory, so restarting the server clears active sessions.
- The app expects Gemini access through `GOOGLE_API_KEY`.
- Production static serving works when the frontend build is copied into `backend/static` as done in the Docker image.

## Future Improvements

- Persistent session storage
- Authentication and multi-user support
- Better choice parsing and structured response handling
- Observability, logging, and retry instrumentation
- Deployment configuration for cloud hosting

## License

Add a license file if you plan to distribute or open-source the project.
