import base64
import json

from google.genai import types
from loguru import logger

from config import FALLBACK_MODEL, IMAGE_MODEL, STORY_MODEL, SYSTEM_INSTRUCTION, TITLE_MODEL
from gemini_utils import format_model_error
from models import StoryEvent, StoryMemory, StorySession, StoryboardBeat


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

    def _json_excerpt(self, text: str, limit: int = 1400) -> str:
        return text[:limit].replace("\r", " ").strip()

    def _build_memory_context(self, session: StorySession) -> str:
        if not session.memory:
            return "No locked story memory yet."
        return "\n".join(f"- {item.label}: {item.detail}" for item in session.memory[:6])

    def _build_director_prompt(self, session: StorySession, choice: str) -> str:
        memory_context = self._build_memory_context(session)
        if session.turns == 1:
            return (
                f"Begin a {session.genre} story under a {session.director_mode} director mode. "
                f"Premise: {session.premise}. "
                "Write a vivid opening scene with clear emotional momentum, generate a cinematic illustration, "
                "and end with exactly 3 distinct choices."
                f"\nLocked memory:\n{memory_context}"
            )

        return (
            f"The reader chose: {choice}. Continue the {session.genre} story in a {session.director_mode} mode. "
            "Show immediate consequences, reveal something that deepens the emotional stakes or world, "
            "generate a scene illustration, and end with exactly 3 distinct choices."
            f"\nLocked memory:\n{memory_context}"
        )

    def _parse_json_block(self, text: str) -> dict | None:
        if not text:
            return None

        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            cleaned = cleaned.replace("json", "", 1).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(cleaned[start:end + 1])
                except json.JSONDecodeError:
                    return None
        return None

    def _default_choices(self, session: StorySession) -> list[str]:
        if session.genre == "romance":
            return [
                "Stay with the feeling and confess what you have been hiding.",
                "Pull back and protect yourself before the moment goes too far.",
                "Change the setting and search for a clue that reframes the relationship.",
            ]
        if session.genre in {"horror", "mystery"}:
            return [
                "Investigate the unsettling detail instead of looking away.",
                "Retreat to safety and gather more information first.",
                "Confront the person or force that seems to be behind this.",
            ]
        return [
            "Push deeper into the unknown despite the risk.",
            "Pause and examine the scene for a revealing detail.",
            "Change course and test a bolder, less expected direction.",
        ]

    async def _ensure_choices(self, session: StorySession, text_context: str) -> list[str]:
        prompt = (
            "Read this story beat and return strict JSON with a key named choices. "
            "choices must contain exactly 3 short, distinct next-scene options for the reader."
            f"\nGenre: {session.genre}\nDirector mode: {session.director_mode}\n"
            f"Scene excerpt:\n{self._json_excerpt(text_context)}"
        )

        try:
            response = await self.client.aio.models.generate_content(
                model=FALLBACK_MODEL,
                contents=[{"role": "user", "parts": [{"text": prompt}]}],
                config=types.GenerateContentConfig(
                    temperature=0.5,
                    max_output_tokens=250,
                    response_mime_type="application/json",
                ),
            )
            payload = self._parse_json_block(self._extract_text(response)) or {}
            choices = [
                (choice or "").strip()
                for choice in (payload.get("choices") or [])
                if (choice or "").strip()
            ]
            if len(choices) >= 3:
                return choices[:3]
        except Exception as exc:
            logger.warning("Choice generation fallback failed: {}", exc)

        return self._default_choices(session)

    async def _refresh_story_state(self, session: StorySession, text_context: str, image_event: StoryEvent | None, choice: str):
        if not text_context.strip():
            return

        prompt = (
            "You maintain state for an interactive cinematic story. "
            "Return strict JSON with two keys: memory and storyboard_caption. "
            "memory must be an array of up to 5 objects with label and detail. "
            "Pick durable facts only: characters, promises, secrets, objects, relationships, wounds, goals. "
            "storyboard_caption must be a short caption for the latest illustrated beat.\n"
            f"Title: {session.title}\n"
            f"Genre: {session.genre}\n"
            f"Director mode: {session.director_mode}\n"
            f"Latest direction: {choice}\n"
            f"Latest scene excerpt:\n{self._json_excerpt(text_context)}\n"
            f"Existing memory:\n{self._build_memory_context(session)}"
        )

        try:
            response = await self.client.aio.models.generate_content(
                model=FALLBACK_MODEL,
                contents=[{"role": "user", "parts": [{"text": prompt}]}],
                config=types.GenerateContentConfig(
                    temperature=0.3,
                    max_output_tokens=500,
                    response_mime_type="application/json",
                ),
            )
            payload = self._parse_json_block(self._extract_text(response)) or {}
            memory_items = payload.get("memory") or []
            if memory_items:
                session.memory = [
                    StoryMemory(
                        label=(item.get("label") or "Story thread")[:40],
                        detail=(item.get("detail") or "").strip()[:180],
                    )
                    for item in memory_items[:5]
                    if item.get("detail")
                ]

            caption = (payload.get("storyboard_caption") or "").strip()
            if not caption:
                caption = self._json_excerpt(text_context, 120)
            session.storyboard.append(
                StoryboardBeat(
                    turn=session.turns,
                    caption=caption[:120],
                    image=image_event.content if image_event else None,
                    mime_type=image_event.mime_type if image_event else None,
                )
            )
            session.storyboard = session.storyboard[-8:]
        except Exception as exc:
            logger.warning("Story state refresh failed: {}", exc)
            session.storyboard.append(
                StoryboardBeat(
                    turn=session.turns,
                    caption=self._json_excerpt(text_context, 120),
                    image=image_event.content if image_event else None,
                    mime_type=image_event.mime_type if image_event else None,
                )
            )
            session.storyboard = session.storyboard[-8:]

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

    async def create_story(self, genre: str, premise: str, director_mode: str = "cinematic") -> dict:
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
        session = StorySession(genre=genre, premise=premise, title=title, director_mode=director_mode)
        logger.info("Created story session_id={} title='{}' genre='{}'", session.session_id, title, genre)
        self.sessions[session.session_id] = session
        return {
            "session_id": session.session_id,
            "title": title,
            "genre": genre,
            "director_mode": director_mode,
            "memory": [],
            "storyboard": [],
        }

    def get_session(self, sid: str):
        return self.sessions.get(sid)

    def get_snapshot(self, sid: str):
        session = self.sessions.get(sid)
        if not session:
            return None
        return session.snapshot()

    def restore_story(
        self,
        title: str,
        genre: str,
        premise: str,
        history: list[dict],
        turns: int,
        director_mode: str = "cinematic",
        memory: list[dict] | None = None,
        storyboard: list[dict] | None = None,
    ):
        session = StorySession(
            genre=genre,
            premise=premise,
            title=title,
            history=history or [],
            turns=turns or 0,
            director_mode=director_mode or "cinematic",
            memory=[
                StoryMemory(label=item.get("label", "Story thread"), detail=item.get("detail", ""))
                for item in (memory or [])
                if item.get("detail")
            ],
            storyboard=[
                StoryboardBeat(
                    turn=item.get("turn", index + 1),
                    caption=item.get("caption", ""),
                    image=item.get("image"),
                    mime_type=item.get("mime_type"),
                )
                for index, item in enumerate(storyboard or [])
                if item.get("caption") or item.get("image")
            ],
        )
        self.sessions[session.session_id] = session
        logger.info("Restored story session_id={} title='{}' turns={}", session.session_id, title, turns)
        return {
            "session_id": session.session_id,
            "title": title,
            "genre": genre,
            "premise": premise,
            "turns": turns,
            "director_mode": session.director_mode,
            "memory": [{"label": item.label, "detail": item.detail} for item in session.memory],
            "storyboard": [
                {
                    "turn": beat.turn,
                    "caption": beat.caption,
                    "image": beat.image,
                    "mime_type": beat.mime_type,
                }
                for beat in session.storyboard
            ],
        }

    async def run_turn(self, session: StorySession, choice: str, director_mode: str | None = None):
        if director_mode:
            session.director_mode = director_mode
        session.turns += 1
        prompt = self._build_director_prompt(session, choice)

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
            image_added = False
            for part in response.candidates[0].content.parts:
                if getattr(part, "text", None):
                    events.append(StoryEvent(type="text", content=part.text))
                    parts.append({"text": part.text})
                elif getattr(part, "inline_data", None) and not image_added:
                    img = base64.b64encode(part.inline_data.data).decode()
                    events.append(StoryEvent(type="image", content=img, mime_type=part.inline_data.mime_type))
                    parts.append({"text": "[illustration]"})
                    image_added = True

            if not any(event.type == "image" for event in events):
                text_context = "\n\n".join(event.content for event in events if event.type == "text")
                generated_image = await self._generate_scene_image(session, text_context)
                if generated_image:
                    events.append(generated_image)
                    parts.append({"text": "[illustration]"})

            session.history.append({"role": "model", "parts": parts})
            text_context = "\n\n".join(event.content for event in events if event.type == "text")
            image_event = next((event for event in events if event.type == "image"), None)
            choices = await self._ensure_choices(session, text_context)
            await self._refresh_story_state(session, text_context, image_event, choice)
            return {
                "events": [
                    {"type": event.type, "content": event.content, **({"mime_type": event.mime_type} if event.mime_type else {})}
                    for event in events
                ],
                "choices": choices,
                "director_mode": session.director_mode,
                "memory": [{"label": item.label, "detail": item.detail} for item in session.memory],
                "storyboard": [
                    {
                        "turn": beat.turn,
                        "caption": beat.caption,
                        "image": beat.image,
                        "mime_type": beat.mime_type,
                    }
                    for beat in session.storyboard
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
                image_event = next((event for event in events if event.type == "image"), None)
                choices = await self._ensure_choices(session, fallback.text)
                await self._refresh_story_state(session, fallback.text, image_event, choice)
                return {
                    "events": [
                        {"type": event.type, "content": event.content, **({"mime_type": event.mime_type} if event.mime_type else {})}
                        for event in events
                    ],
                    "choices": choices,
                    "director_mode": session.director_mode,
                    "memory": [{"label": item.label, "detail": item.detail} for item in session.memory],
                    "storyboard": [
                        {
                            "turn": beat.turn,
                            "caption": beat.caption,
                            "image": beat.image,
                            "mime_type": beat.mime_type,
                        }
                        for beat in session.storyboard
                    ],
                    "error": None,
                }
            except Exception as exc:
                logger.exception("Fallback story generation failed: {}", exc)
                return {"events": [], "error": format_model_error(exc)}
