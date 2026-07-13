import asyncio
import base64
import json

from google.genai import types
from loguru import logger

from config import (
    FALLBACK_MODEL,
    NARRATION_BEAT_THRESHOLD,
    STORY_MODEL,
    SYSTEM_INSTRUCTION,
    TITLE_MODEL,
)
from gemini_utils import format_model_error
from models import StoryEvent, StoryMemory, StorySession, StoryboardBeat
from text_utils import strip_choice_markup
from visual_engine import VisualEngine


NARRATION_BEAT_PROMPT = (
    "You listen to a live storyteller and decide when enough of a scene has been described to illustrate it. "
    "Return strict JSON with keys: beat_complete, scene_prompt, caption, memory. "
    "beat_complete: true only when the narration so far paints one coherent, visualizable scene "
    "(a place, characters or subjects, and an action or mood). "
    "scene_prompt: one vivid paragraph an illustrator can paint, grounded ONLY in what was narrated. "
    "caption: a short storyboard caption (max 12 words). "
    "memory: up to 5 objects with label and detail — durable story facts only "
    "(characters, promises, secrets, objects, relationships, wounds, goals), merging the existing memory "
    "with anything new from the narration.\n"
    "Title: {title}\nGenre: {genre}\nExisting memory:\n{memory}\nNarration so far:\n{narration}"
)


class StoryService:
    def __init__(self, client, session_store=None):
        self.client = client
        self.visuals = VisualEngine(client)
        self.sessions: dict[str, StorySession] = {}
        self.session_store = session_store
        self._persist_tasks: set[asyncio.Task] = set()

    def _persist(self, session: StorySession):
        """Write the session to Firestore without blocking the caller.

        Serialization happens on the caller's thread (cheap); the Firestore
        writes run in a worker thread. Falls back to a synchronous save when
        called outside the event loop (sync endpoints run in a threadpool).
        """
        if not self.session_store:
            return
        state = session.to_state()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self.session_store.save(state)
            return
        task = loop.create_task(asyncio.to_thread(self.session_store.save, state))
        self._persist_tasks.add(task)
        task.add_done_callback(self._persist_tasks.discard)

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
            prompt = (
                f"Begin a {session.genre} story under a {session.director_mode} director mode. "
                f"Premise: {session.premise}. "
                "Write a vivid opening scene with clear emotional momentum, generate a cinematic illustration, "
                "and end with exactly 3 distinct choices."
                f"\nLocked memory:\n{memory_context}"
            )
        else:
            prompt = (
                f"The reader chose: {choice}. Continue the {session.genre} story in a {session.director_mode} mode. "
                "Show immediate consequences, reveal something that deepens the emotional stakes or world, "
                "generate a scene illustration, and end with exactly 3 distinct choices."
                f"\nLocked memory:\n{memory_context}"
            )
        if session.style_bible:
            prompt += (
                f"\nVisual style bible — every illustration must follow it exactly:\n{session.style_bible}"
            )
        return prompt

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
        # Choice markup is reader UI — keep it out of captions and memory.
        text_context = strip_choice_markup(text_context)
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
        return await self.visuals.generate_scene(session, text_context)

    async def _detect_narration_beat(self, session: StorySession, narration: str) -> dict:
        prompt = NARRATION_BEAT_PROMPT.format(
            title=session.title,
            genre=session.genre,
            memory=self._build_memory_context(session),
            narration=self._json_excerpt(narration, 2000),
        )
        try:
            response = await self.client.aio.models.generate_content(
                model=FALLBACK_MODEL,
                contents=[{"role": "user", "parts": [{"text": prompt}]}],
                config=types.GenerateContentConfig(
                    temperature=0.2,
                    max_output_tokens=600,
                    response_mime_type="application/json",
                ),
            )
            return self._parse_json_block(self._extract_text(response)) or {}
        except Exception as exc:
            logger.warning("Narration beat detection failed: {}", exc)
            return {}

    async def run_narration_beat(self, session: StorySession, emit, force: bool = False) -> bool:
        """Illustrate the pending narration buffer once it forms a complete beat.

        `emit` is an async callback receiving websocket-ready event dicts.
        Returns True when a beat was illustrated. The per-session lock keeps
        overlapping narration chunks from triggering concurrent generations;
        chunks arriving mid-generation stay in the buffer for the next check.
        """
        if session.narration_lock.locked() and not force:
            return False
        async with session.narration_lock:
            captured = session.narration_pending
            narration = captured.strip()
            if not narration:
                return False
            if not force and len(narration) < NARRATION_BEAT_THRESHOLD:
                return False

            payload = await self._detect_narration_beat(session, narration)
            if not force and not payload.get("beat_complete"):
                return False

            # Consume only what we captured — chunks appended while the model
            # calls below run remain buffered for the next beat.
            session.narration_pending = session.narration_pending[len(captured):]
            session.turns += 1
            session.history.append(
                {"role": "user", "parts": [{"text": f"[Live narration] {narration}"}]}
            )

            scene_prompt = (payload.get("scene_prompt") or "").strip() or narration
            caption = (payload.get("caption") or "").strip() or self._json_excerpt(narration, 120)

            await emit({"type": "status", "content": "illustrating"})
            image_event = await self.visuals.generate_scene(session, scene_prompt)
            if image_event:
                session.history.append({"role": "model", "parts": [{"text": "[illustration]"}]})
                await emit({
                    "type": "image",
                    "content": image_event.content,
                    "mime_type": image_event.mime_type,
                })

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

            session.storyboard.append(
                StoryboardBeat(
                    turn=session.turns,
                    caption=caption[:120],
                    image=image_event.content if image_event else None,
                    mime_type=image_event.mime_type if image_event else None,
                )
            )
            session.storyboard = session.storyboard[-8:]

            await emit({
                "type": "memory",
                "items": [{"label": item.label, "detail": item.detail} for item in session.memory],
            })
            await emit({
                "type": "storyboard",
                "items": [
                    {
                        "turn": beat.turn,
                        "caption": beat.caption,
                        "image": beat.image,
                        "mime_type": beat.mime_type,
                    }
                    for beat in session.storyboard
                ],
            })
            self._persist(session)
            await emit({"type": "status", "content": "beat_complete"})
            logger.info(
                "Narration beat illustrated for session_id={} turn={} (forced={})",
                session.session_id, session.turns, force,
            )
            return True

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
        self._persist(session)
        return {
            "session_id": session.session_id,
            "title": title,
            "genre": genre,
            "director_mode": director_mode,
            "memory": [],
            "storyboard": [],
        }

    def get_session(self, sid: str):
        """Return the live session, lazily rehydrating from Firestore after a
        restart or scale-down. Blocks on a store miss — async callers should
        wrap this in asyncio.to_thread."""
        session = self.sessions.get(sid)
        if session or not self.session_store:
            return session
        state = self.session_store.load(sid)
        if not state:
            return None
        restored = StorySession.from_state(state)
        if not restored.anchor_image or not restored.last_image:
            self.visuals.adopt_restored_images(restored)
        return self.sessions.setdefault(sid, restored)

    def get_snapshot(self, sid: str):
        session = self.get_session(sid)
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
        style_bible: str = "",
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
            style_bible=style_bible or "",
        )
        self.visuals.adopt_restored_images(session)
        self.sessions[session.session_id] = session
        self._persist(session)
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

        # Send previous illustrations as transient reference parts so the
        # interleaved model keeps characters and style visually connected.
        # They are not stored in history to keep the context small.
        reference_parts = self.visuals.reference_parts(session)
        contents = session.history
        if reference_parts:
            contents = session.history[:-1] + [
                {"role": "user", "parts": reference_parts + [{"text": prompt}]}
            ]

        try:
            response = await self.client.aio.models.generate_content(
                model=STORY_MODEL,
                contents=contents,
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
                    self.visuals.register_image(session, img, part.inline_data.mime_type)
                    image_added = True

            text_context = "\n\n".join(event.content for event in events if event.type == "text")
            await self.visuals.ensure_style_bible(session, text_context)

            if not any(event.type == "image" for event in events):
                generated_image = await self._generate_scene_image(session, text_context)
                if generated_image:
                    events.append(generated_image)
                    parts.append({"text": "[illustration]"})

            session.history.append({"role": "model", "parts": parts})
            image_event = next((event for event in events if event.type == "image"), None)
            choices, _ = await asyncio.gather(
                self._ensure_choices(session, text_context),
                self._refresh_story_state(session, text_context, image_event, choice),
            )
            self._persist(session)
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
                choices, _ = await asyncio.gather(
                    self._ensure_choices(session, fallback.text),
                    self._refresh_story_state(session, fallback.text, image_event, choice),
                )
                self._persist(session)
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
