import base64
import uuid

from google.genai import types

from config import FALLBACK_MODEL, STORY_MODEL, SYSTEM_INSTRUCTION, TITLE_MODEL
from gemini_utils import format_model_error


class StoryService:
    def __init__(self, client):
        self.client = client
        self.sessions = {}

    async def create_story(self, genre: str, premise: str) -> dict:
        sid = str(uuid.uuid4())
        title_resp = await self.client.aio.models.generate_content(
            model=TITLE_MODEL,
            contents=[{
                "role": "user",
                "parts": [{
                    "text": f"One short cinematic title for a {genre} story: {premise}. Reply with ONLY the title."
                }],
            }],
            config=types.GenerateContentConfig(temperature=1.0, max_output_tokens=30),
        )
        title = title_resp.text.strip().strip('"')
        self.sessions[sid] = {
            "genre": genre,
            "premise": premise,
            "title": title,
            "history": [],
            "turns": 0,
        }
        return {"session_id": sid, "title": title, "genre": genre}

    def get_session(self, sid: str):
        return self.sessions.get(sid)

    async def run_turn(self, session: dict, choice: str):
        session["turns"] += 1
        if session["turns"] == 1:
            prompt = (
                f"Begin a {session['genre']} story. Premise: {session['premise']}. "
                "Create a stunning opening scene with a generated illustration. End with 3 choices."
            )
        else:
            prompt = (
                f"The reader chose: {choice}. Continue the story, show consequences, "
                "generate a scene illustration, end with 3 choices."
            )

        session["history"].append({"role": "user", "parts": [{"text": prompt}]})

        try:
            response = await self.client.aio.models.generate_content(
                model=STORY_MODEL,
                contents=session["history"],
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    temperature=0.9,
                    max_output_tokens=4096,
                    response_modalities=["TEXT", "IMAGE"],
                ),
            )
            parts = []
            events = []
            for part in response.candidates[0].content.parts:
                if getattr(part, "text", None):
                    events.append({"type": "text", "content": part.text})
                    parts.append({"text": part.text})
                elif getattr(part, "inline_data", None):
                    img = base64.b64encode(part.inline_data.data).decode()
                    events.append({
                        "type": "image",
                        "content": img,
                        "mime_type": part.inline_data.mime_type,
                    })
                    parts.append({"text": "[illustration]"})
            session["history"].append({"role": "model", "parts": parts})
            return {"events": events, "error": None}
        except Exception:
            try:
                fallback = await self.client.aio.models.generate_content(
                    model=FALLBACK_MODEL,
                    contents=session["history"],
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_INSTRUCTION,
                        temperature=0.9,
                        max_output_tokens=2048,
                    ),
                )
                session["history"].append({"role": "model", "parts": [{"text": fallback.text}]})
                return {"events": [{"type": "text", "content": fallback.text}], "error": None}
            except Exception as exc:
                return {"events": [], "error": format_model_error(exc)}
