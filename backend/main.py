
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from google import genai
from loguru import logger

from config import PORT
from gemini_utils import format_model_error
from narration_service import NarrationService
from schemas import CreateReq, NarrationReq, RestoreReq
from story_service import StoryService

client = None
story_service = None
narration_service = None

@asynccontextmanager
async def lifespan(app):
    global client, narration_service, story_service
    logger.remove()
    logger.add(
        os.path.join(os.path.dirname(__file__), "server.log"),
        level="INFO",
        rotation="5 MB",
        backtrace=True,
        diagnose=True,
    )
    logger.add(lambda msg: print(msg, end=""), level="INFO")
    client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
    story_service = StoryService(client)
    try:
        narration_service = NarrationService()
        logger.info("Cloud TTS ready")
    except Exception as exc:
        narration_service = None
        logger.warning("Cloud TTS unavailable: {}", exc)
    logger.info("Luminary ready")
    yield

app = FastAPI(title="Luminary", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
def health(): return {"status":"healthy"}

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
        )
    except Exception as exc:
        logger.exception("Story restore failed: {}", exc)
        raise HTTPException(status_code=500, detail="Failed to restore story.") from exc

@app.post("/api/story/restore")
async def api_restore_story(req: RestoreReq):
    return await restore_story(req)

@app.get("/narration/voices")
def list_narration_voices():
    if not narration_service:
        raise HTTPException(status_code=503, detail="Cloud TTS is not configured.")
    return {"voices": narration_service.list_voices()}

@app.get("/api/narration/voices")
def api_list_narration_voices():
    return list_narration_voices()

@app.post("/narration/speak")
def synthesize_narration(req: NarrationReq):
    if not narration_service:
        raise HTTPException(status_code=503, detail="Cloud TTS is not configured.")
    try:
        return narration_service.synthesize(
            text=req.text,
            genre=req.genre,
            voice_name=req.voice_name,
            language_code=req.language_code,
        )
    except Exception as exc:
        logger.exception("Narration synthesis failed: {}", exc)
        raise HTTPException(status_code=503, detail="Failed to synthesize narration.") from exc

@app.post("/api/narration/speak")
def api_synthesize_narration(req: NarrationReq):
    return synthesize_narration(req)

@app.websocket("/ws/{sid}")
async def ws_story(websocket: WebSocket, sid: str):
    await websocket.accept()
    session = story_service.get_session(sid)
    if not session:
        logger.warning("WebSocket opened for missing session_id={}", sid)
        await websocket.send_json({"type":"error","content":"Session not found"})
        await websocket.close(); return
    logger.info("WebSocket connected for session_id={}", sid)
    await websocket.send_json({"type":"system","content":f"Connected: {session.title}"})
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
                await websocket.send_json({"type":"director_mode","content": result.get("director_mode", session.director_mode)})
                await websocket.send_json({"type":"memory","items": result.get("memory", [])})
                await websocket.send_json({"type":"storyboard","items": result.get("storyboard", [])})
                if result["error"]:
                    logger.error("Story turn failed for session_id={}: {}", sid, result["error"])
                    await websocket.send_json({"type":"error","content":result["error"]})
                await websocket.send_json({"type":"status","content":"complete"})
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
