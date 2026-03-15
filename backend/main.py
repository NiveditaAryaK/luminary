
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from google import genai
from loguru import logger

from config import PORT
from gemini_utils import format_model_error
from schemas import CreateReq
from story_service import StoryService

client = None
story_service = None

@asynccontextmanager
async def lifespan(app):
    global client, story_service
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
        return await story_service.create_story(req.genre, req.premise)
    except Exception as exc:
        logger.exception("Story creation failed: {}", exc)
        raise HTTPException(status_code=503, detail=format_model_error(exc)) from exc

@app.post("/api/story/create")
async def api_create(req: CreateReq):
    return await create(req)

@app.websocket("/ws/{sid}")
async def ws_story(websocket: WebSocket, sid: str):
    await websocket.accept()
    session = story_service.get_session(sid)
    if not session:
        logger.warning("WebSocket opened for missing session_id={}", sid)
        await websocket.send_json({"type":"error","content":"Session not found"})
        await websocket.close(); return
    logger.info("WebSocket connected for session_id={}", sid)
    await websocket.send_json({"type":"system","content":f"Connected: {session['title']}"})
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "choice":
                choice = data.get("content","")
                logger.info("Running story turn for session_id={} turn={} choice='{}'", sid, session["turns"] + 1, choice)
                await websocket.send_json({"type":"status","content":"generating"})
                result = await story_service.run_turn(session, choice)
                for event in result["events"]:
                    await websocket.send_json(event)
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
