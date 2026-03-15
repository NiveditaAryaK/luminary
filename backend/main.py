
import os, uuid
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from google import genai
from google.genai import types

load_dotenv()

TITLE_MODEL = os.getenv("GEMINI_TITLE_MODEL", "gemini-2.5-flash")
STORY_MODEL = os.getenv("GEMINI_STORY_MODEL", "gemini-2.5-flash-image")
FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-2.5-flash")

SYSTEM_INSTRUCTION = """You are Luminary, a master cinematic storyteller.
Create immersive interactive stories with INTERLEAVED text and generated images.
Write in second person. Each beat: 2-3 paragraphs of vivid prose + a generated scene illustration.
End every beat with 3 choices prefixed with: CHOICE_A: CHOICE_B: CHOICE_C:
Keep character appearances consistent. Cinematic, dramatic lighting in all images."""

sessions = {}
client = None

@asynccontextmanager
async def lifespan(app):
    global client
    client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
    print("Luminary ready")
    yield

app = FastAPI(title="Luminary", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

class CreateReq(BaseModel):
    genre: str
    premise: str


def format_model_error(exc: Exception) -> str:
    message = str(exc)
    lowered = message.lower()
    if "resource_exhausted" in lowered or "quota" in lowered or "429" in lowered:
        return "Gemini quota exceeded for this API key. Please check billing, limits, or try again later."
    if "api key" in lowered or "permission" in lowered or "unauthorized" in lowered or "403" in lowered:
        return "Gemini request was rejected. Verify GOOGLE_API_KEY and project access."
    if "not_found" in lowered or "no longer available" in lowered or "404" in lowered:
        return "The configured Gemini model is unavailable. Update the backend model configuration."
    return "Gemini request failed. Please verify your model access and try again."


@app.get("/health")
def health(): return {"status":"healthy"}

@app.get("/api/health")
def api_health(): return health()

@app.post("/story/create")
async def create(req: CreateReq):
    sid = str(uuid.uuid4())
    try:
        title_resp = await client.aio.models.generate_content(
            model=TITLE_MODEL,
            contents=[{"role":"user","parts":[{"text":f"One short cinematic title for a {req.genre} story: {req.premise}. Reply with ONLY the title."}]}],
            config=types.GenerateContentConfig(temperature=1.0, max_output_tokens=30)
        )
        title = title_resp.text.strip().strip(chr(34))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=format_model_error(exc)) from exc
    sessions[sid] = {"genre":req.genre,"premise":req.premise,"title":title,"history":[],"turns":0}
    return {"session_id":sid,"title":title,"genre":req.genre}

@app.post("/api/story/create")
async def api_create(req: CreateReq):
    return await create(req)

@app.websocket("/ws/{sid}")
async def ws_story(websocket: WebSocket, sid: str):
    await websocket.accept()
    if sid not in sessions:
        await websocket.send_json({"type":"error","content":"Session not found"})
        await websocket.close(); return
    s = sessions[sid]
    await websocket.send_json({"type":"system","content":f"Connected: {s[chr(116)+chr(105)+chr(116)+chr(108)+chr(101)]}"})
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "choice":
                choice = data.get("content","")
                s["turns"] += 1
                if s["turns"] == 1:
                    prompt = f"Begin a {s[chr(103)+chr(101)+chr(110)+chr(114)+chr(101)]} story. Premise: {s[chr(112)+chr(114)+chr(101)+chr(109)+chr(105)+chr(115)+chr(101)]}. Create a stunning opening scene with a generated illustration. End with 3 choices."
                else:
                    prompt = f"The reader chose: {choice}. Continue the story, show consequences, generate a scene illustration, end with 3 choices."
                s["history"].append({"role":"user","parts":[{"text":prompt}]})
                await websocket.send_json({"type":"status","content":"generating"})
                try:
                    resp = await client.aio.models.generate_content(
                        model=STORY_MODEL,
                        contents=s["history"],
                        config=types.GenerateContentConfig(
                            system_instruction=SYSTEM_INSTRUCTION,
                            temperature=0.9, max_output_tokens=4096,
                            response_modalities=["TEXT","IMAGE"]
                        )
                    )
                    parts_text = []
                    for part in resp.candidates[0].content.parts:
                        if hasattr(part,"text") and part.text:
                            await websocket.send_json({"type":"text","content":part.text})
                            parts_text.append({"text":part.text})
                        elif hasattr(part,"inline_data") and part.inline_data:
                            import base64
                            img = base64.b64encode(part.inline_data.data).decode()
                            await websocket.send_json({"type":"image","content":img,"mime_type":part.inline_data.mime_type})
                            parts_text.append({"text":"[illustration]"})
                    s["history"].append({"role":"model","parts":parts_text})
                except Exception:
                    try:
                        resp2 = await client.aio.models.generate_content(
                            model=FALLBACK_MODEL,
                            contents=s["history"],
                            config=types.GenerateContentConfig(
                                system_instruction=SYSTEM_INSTRUCTION,
                                temperature=0.9,
                                max_output_tokens=2048
                            )
                        )
                        await websocket.send_json({"type":"text","content":resp2.text})
                        s["history"].append({"role":"model","parts":[{"text":resp2.text}]})
                    except Exception as fallback_exc:
                        await websocket.send_json({"type":"error","content":format_model_error(fallback_exc)})
                await websocket.send_json({"type":"status","content":"complete"})
            elif data.get("type")=="ping":
                await websocket.send_json({"type":"pong"})
    except WebSocketDisconnect:
        pass

STATIC = os.path.join(os.path.dirname(__file__),"static")
if os.path.isdir(STATIC):
    app.mount("/",StaticFiles(directory=STATIC,html=True),name="static")

if __name__=="__main__":
    import uvicorn
    uvicorn.run("main:app",host="0.0.0.0",port=int(os.getenv("PORT",8080)),reload=False)
