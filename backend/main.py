import asyncio
import os
import sys
from html import escape as html_escape
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from google import genai
from loguru import logger

from config import PORT
from film_service import FilmBusyError, FilmInputError, FilmService, FilmUnavailableError
from gemini_utils import format_model_error
from narration_service import NarrationService
from schemas import CreateReq, FilmReq, NarrationReq, PublishReq, RestoreReq
from session_store import SessionStore
from story_service import StoryService
from youtube_service import (
    YouTubeBusyError,
    YouTubeError,
    YouTubeNotConfiguredError,
    YouTubeNotConnectedError,
    YouTubeService,
)

client = None
story_service = None
narration_service = None
film_service = None
session_store = None
youtube_service = None

@asynccontextmanager
async def lifespan(app):
    global client, narration_service, story_service, film_service, session_store, youtube_service
    logger.remove()
    logger.add(
        os.path.join(os.path.dirname(__file__), "server.log"),
        level="INFO",
        rotation="5 MB",
        backtrace=False,
        diagnose=False,
    )
    logger.add(
        sys.stdout,
        level="INFO",
        backtrace=False,
        diagnose=False,
    )
    client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
    session_store = SessionStore()
    story_service = StoryService(client, session_store)
    # The TTS client is created lazily on first use, so a startup-time
    # credential hiccup no longer disables narration for good.
    narration_service = NarrationService()
    film_service = FilmService(narration_service)
    youtube_service = YouTubeService(client, session_store)
    if not youtube_service.configured():
        logger.info("YouTube publishing disabled (YT_CLIENT_ID/YT_CLIENT_SECRET/YT_REDIRECT_URI not set)")
    if not film_service.ffmpeg_available():
        logger.warning("ffmpeg not found — film rendering disabled until it is installed")
    logger.info("Luminary ready")
    yield

app = FastAPI(title="Luminary", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "session_persistence": session_store.status if session_store else "disabled",
    }

@app.get("/api/health")
def api_health(): return health()

@app.post("/story/create")
async def create(req: CreateReq):
    try:
        logger.info("Creating story session for genre='{genre}'", genre=req.genre)
        return await story_service.create_story(req.genre, req.premise, req.director_mode)
    except Exception as exc:
        logger.exception("Story creation failed: {}", exc)
        raise HTTPException(status_code=503, detail=format_model_error(exc)) from exc

@app.post("/api/story/create")
async def api_create(req: CreateReq):
    return await create(req)

@app.get("/story/{sid}")
def get_story_snapshot(sid: str):
    snapshot = story_service.get_snapshot(sid)
    if not snapshot:
      raise HTTPException(status_code=404, detail="Session not found")
    return snapshot

@app.get("/api/story/{sid}")
def api_get_story_snapshot(sid: str):
    return get_story_snapshot(sid)

@app.post("/story/restore")
async def restore_story(req: RestoreReq):
    try:
        return story_service.restore_story(
            req.title,
            req.genre,
            req.premise,
            req.history,
            req.turns,
            req.director_mode,
            req.memory,
            req.storyboard,
            req.style_bible,
        )
    except Exception as exc:
        logger.exception("Story restore failed: {}", exc)
        raise HTTPException(status_code=500, detail="Failed to restore story.") from exc

@app.post("/api/story/restore")
async def api_restore_story(req: RestoreReq):
    return await restore_story(req)

@app.get("/narration/voices")
def list_narration_voices():
    try:
        return {"voices": narration_service.list_voices()}
    except Exception as exc:
        logger.warning("Cloud TTS voices unavailable: {}", exc)
        raise HTTPException(
            status_code=503,
            detail=f"Cloud TTS unavailable: {str(exc)[:300]}",
        ) from exc

@app.get("/api/narration/voices")
def api_list_narration_voices():
    return list_narration_voices()

@app.post("/narration/speak")
def synthesize_narration(req: NarrationReq):
    try:
        return narration_service.synthesize(
            text=req.text,
            genre=req.genre,
            voice_name=req.voice_name,
            language_code=req.language_code,
        )
    except Exception as exc:
        logger.exception("Narration synthesis failed: {}", exc)
        raise HTTPException(
            status_code=503,
            detail=f"Failed to synthesize narration: {str(exc)[:300]}",
        ) from exc

@app.post("/api/narration/speak")
def api_synthesize_narration(req: NarrationReq):
    return synthesize_narration(req)

@app.post("/story/{sid}/film")
async def start_film_render(sid: str, req: FilmReq | None = None):
    session = await asyncio.to_thread(story_service.get_session, sid)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        return film_service.start_render(
            session,
            voice_name=req.voice_name if req else None,
            language_code=req.language_code if req else None,
        )
    except FilmUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except FilmBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except FilmInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@app.post("/api/story/{sid}/film")
async def api_start_film_render(sid: str, req: FilmReq | None = None):
    return await start_film_render(sid, req)

@app.get("/story/{sid}/film/status")
def film_status(sid: str):
    job = film_service.get_job(sid)
    if not job:
        raise HTTPException(status_code=404, detail="No film render for this story yet.")
    return film_service.job_public(job)

@app.get("/api/story/{sid}/film/status")
def api_film_status(sid: str):
    return film_status(sid)

@app.get("/story/{sid}/film/download")
def film_download(sid: str):
    job = film_service.get_job(sid)
    if not job or job["status"] != "done" or not job.get("output_path"):
        raise HTTPException(status_code=404, detail="Film is not ready yet.")
    if not os.path.isfile(job["output_path"]):
        raise HTTPException(status_code=404, detail="Rendered film file is missing.")
    session = story_service.get_session(sid)
    slug = "".join(
        ch if ch.isalnum() or ch in " -_" else ""
        for ch in (session.title if session else "luminary-film")
    ).strip().replace(" ", "-") or "luminary-film"
    return FileResponse(job["output_path"], media_type="video/mp4", filename=f"{slug}.mp4")

@app.get("/api/story/{sid}/film/download")
def api_film_download(sid: str):
    return film_download(sid)

@app.get("/youtube/status")
def youtube_status(uid: str):
    return {
        "configured": youtube_service.configured(),
        "connected": youtube_service.configured() and youtube_service.connected(uid),
    }

@app.get("/api/youtube/status")
def api_youtube_status(uid: str):
    return youtube_status(uid)

@app.get("/youtube/auth/start")
def youtube_auth_start(uid: str):
    try:
        return RedirectResponse(youtube_service.auth_url(uid))
    except YouTubeNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

@app.get("/api/youtube/auth/start")
def api_youtube_auth_start(uid: str):
    return youtube_auth_start(uid)

@app.get("/youtube/oauth/callback")
async def youtube_oauth_callback(state: str = "", code: str = "", error: str = ""):
    detail = ""
    if error:
        message = "YouTube connection was cancelled."
        detail = error
    elif not code:
        message = "YouTube connection was cancelled."
    else:
        try:
            await asyncio.to_thread(youtube_service.handle_callback, state, code)
            message = "YouTube connected. You can close this window."
        except Exception as exc:
            logger.exception("YouTube OAuth callback failed: {}", exc)
            message = "YouTube connection failed."
            detail = str(exc)[:300]
    auto_close = "setTimeout(function(){window.close()},1500)" if not detail else ""
    detail_html = (
        f"<p style=\"max-width:32rem;color:#c8c2b0;font-size:0.85rem\">{html_escape(detail)}</p>"
        if detail else ""
    )
    return HTMLResponse(
        "<html><body style=\"background:#0d0f18;color:#f7e9bf;"
        "font-family:sans-serif;display:grid;place-items:center;height:100vh\">"
        f"<div style=\"text-align:center\"><p>{message}</p>{detail_html}</div>"
        "<script>if(window.opener){window.opener.postMessage('yt-oauth-done','*')}"
        f"{auto_close}</script>"
        "</body></html>"
    )

@app.get("/api/youtube/oauth/callback")
async def api_youtube_oauth_callback(state: str = "", code: str = "", error: str = ""):
    return await youtube_oauth_callback(state, code, error)

@app.post("/story/{sid}/publish")
async def start_publish(sid: str, req: PublishReq):
    session = await asyncio.to_thread(story_service.get_session, sid)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    film_job = film_service.get_job(sid)
    if not film_job or film_job["status"] != "done" or not film_job.get("output_path"):
        raise HTTPException(status_code=400, detail="Render the film before publishing.")
    metadata = await youtube_service.generate_metadata(session)
    try:
        return youtube_service.start_publish(sid, req.uid, film_job["output_path"], metadata)
    except YouTubeNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except YouTubeNotConnectedError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except YouTubeBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except YouTubeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@app.post("/api/story/{sid}/publish")
async def api_start_publish(sid: str, req: PublishReq):
    return await start_publish(sid, req)

@app.get("/story/{sid}/publish/status")
def publish_status(sid: str):
    job = youtube_service.get_job(sid)
    if not job:
        raise HTTPException(status_code=404, detail="No publish job for this story yet.")
    return youtube_service.job_public(job)

@app.get("/api/story/{sid}/publish/status")
def api_publish_status(sid: str):
    return publish_status(sid)

@app.websocket("/ws/{sid}")
async def ws_story(websocket: WebSocket, sid: str):
    await websocket.accept()
    session = await asyncio.to_thread(story_service.get_session, sid)
    if not session:
        logger.warning("WebSocket opened for missing session_id={}", sid)
        await websocket.send_json({"type":"error","content":"Session not found"})
        await websocket.close(); return
    logger.info("WebSocket connected for session_id={}", sid)
    await websocket.send_json({"type":"system","content":f"Connected: {session.title}"})

    async def emit(payload: dict):
        try:
            await websocket.send_json(payload)
        except Exception:
            logger.debug("Dropped narration event for closed socket session_id={}", sid)

    async def narration_beat(force: bool):
        try:
            await story_service.run_narration_beat(session, emit, force=force)
        except Exception as exc:
            logger.exception("Narration beat failed for session_id={}: {}", sid, exc)
            await emit({"type": "error", "content": format_model_error(exc)})

    narration_tasks: set[asyncio.Task] = set()

    def spawn_narration_beat(force: bool):
        task = asyncio.create_task(narration_beat(force))
        narration_tasks.add(task)
        task.add_done_callback(narration_tasks.discard)

    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "choice":
                choice = data.get("content","")
                director_mode = data.get("director_mode")
                logger.info("Running story turn for session_id={} turn={} choice='{}'", sid, session.turns + 1, choice)
                await websocket.send_json({"type":"status","content":"generating"})
                result = await story_service.run_turn(session, choice, director_mode)
                for event in result["events"]:
                    await websocket.send_json(event)
                await websocket.send_json({"type":"choices","choices": result.get("choices", [])})
                await websocket.send_json({"type":"director_mode","content": result.get("director_mode", session.director_mode)})
                await websocket.send_json({"type":"memory","items": result.get("memory", [])})
                await websocket.send_json({"type":"storyboard","items": result.get("storyboard", [])})
                if result["error"]:
                    logger.error("Story turn failed for session_id={}: {}", sid, result["error"])
                    await websocket.send_json({"type":"error","content":result["error"]})
                await websocket.send_json({"type":"status","content":"complete"})
            elif data.get("type") == "narration":
                chunk = (data.get("content") or "").strip()
                if chunk:
                    session.narration_pending = (
                        f"{session.narration_pending} {chunk}".strip()
                        if session.narration_pending else chunk
                    )
                    # Beat runs in the background so the receive loop keeps
                    # accepting chunks; the per-session lock in the service
                    # prevents overlapping generations.
                    if not session.narration_lock.locked():
                        spawn_narration_beat(False)
            elif data.get("type") == "narration_flush":
                spawn_narration_beat(True)
            elif data.get("type")=="ping":
                await websocket.send_json({"type":"pong"})
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for session_id={}", sid)

STATIC = os.path.join(os.path.dirname(__file__),"static")
if os.path.isdir(STATIC):
    app.mount("/",StaticFiles(directory=STATIC,html=True),name="static")

if __name__=="__main__":
    import uvicorn
    uvicorn.run("main:app",host="0.0.0.0",port=PORT,reload=False)
