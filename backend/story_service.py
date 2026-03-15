import base64

from google.genai import types
from loguru import logger

from config import FALLBACK_MODEL, IMAGE_MODEL, STORY_MODEL, SYSTEM_INSTRUCTION, TITLE_MODEL
from gemini_utils import format_model_error
from models import StoryEvent, StorySession


class StoryService:
    def __init__(self, client):
        self.client = client
        self.sessions: dict[str, StorySession] = {}

    def _extract_text(self, response) -> str:
        text = getattr(response, "text", None)
        if text:
            return text.strip()

        candidates = getattr(response, "candidates", None) or []
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            parts = getattr(content, "parts", None) or []
            for part in parts:
                part_text = getattr(part, "text", None)
                if part_text:
                    return part_text.strip()

        return ""

    async def _generate_scene_image(self, session: StorySession, text_context: str) -> StoryEvent | None:
        prompt = (
            f"Create a cinematic illustration for this {session.genre} story beat.\n"
            f"Story title: {session.title}\n"
            f"Scene context: {text_context[:1200]}\n"
            "Match the emotional tone and keep character appearance consistent."
        )

        try:
            response = await self.client.aio.models.generate_content(
                model=IMAGE_MODEL,
                contents=[{"role": "user", "parts": [{"text": prompt}]}],
                config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
            )

            candidates = getattr(response, "candidates", None) or []
            for candidate in candidates:
                content = getattr(candidate, "content", None)
                parts = getattr(content, "parts", None) or []
                for part in parts:
                    inline_data = getattr(part, "inline_data", None)
                    if inline_data:
                        image = base64.b64encode(inline_data.data).decode()
                        return StoryEvent(
                            type="image",
                            content=image,
                            mime_type=inline_data.mime_type,
                        )
        except Exception as exc:
            logger.warning("Scene image generation failed: {}", exc)

        return None

    async def create_story(self, genre: str, premise: str) -> dict:
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
        title = self._extract_text(title_resp).strip('"')
        if not title:
            logger.warning("Title model returned no text for genre='{}'; using fallback title", genre)
            title = f"The {genre.title()} Affair"
        session = StorySession(genre=genre, premise=premise, title=title)
        logger.info("Created story session_id={} title='{}' genre='{}'", session.session_id, title, genre)
        self.sessions[session.session_id] = session
        return {"session_id": session.session_id, "title": title, "genre": genre}

    def get_session(self, sid: str):
        return self.sessions.get(sid)

    def get_snapshot(self, sid: str):
        session = self.sessions.get(sid)
        if not session:
            return None
        return session.snapshot()

    def restore_story(self, title: str, genre: str, premise: str, history: list[dict], turns: int):
        session = StorySession(
            genre=genre,
            premise=premise,
            title=title,
            history=history or [],
            turns=turns or 0,
        )
        self.sessions[session.session_id] = session
        logger.info("Restored story session_id={} title='{}' turns={}", session.session_id, title, turns)
        return {
            "session_id": session.session_id,
            "title": title,
            "genre": genre,
            "premise": premise,
            "turns": turns,
        }

    async def run_turn(self, session: StorySession, choice: str):
        session.turns += 1
        if session.turns == 1:
            prompt = (
                f"Begin a {session.genre} story. Premise: {session.premise}. "
                "Create a stunning opening scene with a generated illustration. End with 3 choices."
            )
        else:
            prompt = (
                f"The reader chose: {choice}. Continue the story, show consequences, "
                "generate a scene illustration, end with 3 choices."
            )

        session.history.append({"role": "user", "parts": [{"text": prompt}]})

        try:
            response = await self.client.aio.models.generate_content(
                model=STORY_MODEL,
                contents=session.history,
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
                    events.append(StoryEvent(type="text", content=part.text))
                    parts.append({"text": part.text})
                elif getattr(part, "inline_data", None):
                    img = base64.b64encode(part.inline_data.data).decode()
                    events.append(StoryEvent(type="image", content=img, mime_type=part.inline_data.mime_type))
                    parts.append({"text": "[illustration]"})

            if not any(event.type == "image" for event in events):
                text_context = "\n\n".join(event.content for event in events if event.type == "text")
                generated_image = await self._generate_scene_image(session, text_context)
                if generated_image:
                    events.append(generated_image)
                    parts.append({"text": "[illustration]"})

            session.history.append({"role": "model", "parts": parts})
            return {
                "events": [
                    {"type": event.type, "content": event.content, **({"mime_type": event.mime_type} if event.mime_type else {})}
                    for event in events
                ],
                "error": None,
            }
        except Exception as exc:
            logger.warning("Primary story model failed, falling back to text-only model: {}", exc)
            try:
                fallback = await self.client.aio.models.generate_content(
                    model=FALLBACK_MODEL,
                    contents=session.history,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_INSTRUCTION,
                        temperature=0.9,
                        max_output_tokens=2048,
                    ),
                )
                events = [StoryEvent(type="text", content=fallback.text)]
                parts = [{"text": fallback.text}]
                generated_image = await self._generate_scene_image(session, fallback.text)
                if generated_image:
                    events.append(generated_image)
                    parts.append({"text": "[illustration]"})
                session.history.append({"role": "model", "parts": parts})
                return {
                    "events": [
                        {"type": event.type, "content": event.content, **({"mime_type": event.mime_type} if event.mime_type else {})}
                        for event in events
                    ],
                    "error": None,
                }
            except Exception as exc:
                logger.exception("Fallback story generation failed: {}", exc)
                return {"events": [], "error": format_model_error(exc)}
