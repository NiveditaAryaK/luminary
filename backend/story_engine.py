"""
Luminary Story Engine — Core AI storytelling logic using Google GenAI SDK.

Uses Gemini's interleaved multimodal output to generate stories that weave
together text narration, generated images, and scene descriptions in a single
fluid output stream.
"""

import asyncio
import base64
import io
import json
import os
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import AsyncGenerator, Optional

from google import genai
from google.genai import types


# ---------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------

GEMINI_MODEL = "gemini-2.0-flash-exp"
FALLBACK_MODEL = "gemini-2.0-flash"

SYSTEM_INSTRUCTION = """You are Luminary, a master cinematic storyteller and creative director.

Your role is to create immersive, interactive stories by generating INTERLEAVED text
and images. Every response you give should weave together vivid prose narration with
generated illustrations that bring the story to life.

STORYTELLING RULES_FOR_LUMINARY:
1. Write in second person for immersion
2. Each beat: 2-3 paragraphs of rich, atmospheric prose
3. Generate an illustration for EACH major scene
4. End every beat with 2-3 meaningful choices
5. Maintain narrative continuity
6. Create distinct characters
7. Build tension like a film director
8. Use sensory details

FORMAT:
- Narration as flowing prose
- Present choices as:
  ⟐ Choice A: [desc]
  ⟐ Choice B: [desc]
  
"""


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

class StoryGenre(str, Enum):
    FANTASY = "fantasy"
    SCIFI = "sci-fi"
    MYSTERY = "mystery"
    HORROR = "horror"
    ROMANCE = "romance"
    ADVENTURE = "adventure"
    HISTORICAL = "historical"


@dataclass
class StorySegment:
    segment_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    segment_type: str = "text"
    content: str = ""
    mime_type: str = "text/plain"


@dataclass
class StoryState:
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    genre: StoryGenre = StoryGenre.FANTASY
    title: str = ""
    premise: str = ""
    segments: list[StorySegment] = field(default_factory=list)
    turn_count: int = 0
    chat_history: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Story Engine
# ---------------------------------------------------------------------------

class LuminaryEngine:
    def __init__(self, api_key=None):
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError("GOOGLE_API_KEY is required")
        self.client = genai.Client(api_key=self.api_key)
        self.sessions: dict[str, StoryState] = {}

    def create_session(self, genre: StoryGenre, premise: str = "") -> StoryState:
        state = StoryState(genre=genre, premise=premise)
        self.sessions[state.session_id] = state
        return state

    def get_session(self, session_id: str):
        return self.sessions.get(session_id)

    async def generate_story_beat(self, session_id: str, user_input: str):
        state = self.sessions.get(session_id)
        if not state:
            raise ValueError(f"Session {session_id} not found")
        state.turn_count += 1
        if state.turn_count == 1:
            prompt = self._build_opening_prompt(state, user_input)
        else:
            prompt = self._build_continuation_prompt(state, user_input)
        state.chat_history.append({"role": "user", "parts": [{"text": prompt}]})
        try:
            response = await self.client.aio.models.generate_content(
                model=GEMINI_MODEL,
                contents=state.chat_history,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    temperature=0.9,
                    top_p=0.95,
                    max_output_tokens=4096,
                    response_modalities=["TEXT", "IMAGE"],
                ),
            )
            assistant_parts = []
            for part in response.candidates[0].content.parts:
                if part.text:
                    seg = StorySegment(segment_type="text", content=part.text, mime_type="text/plain")
                    state.segments.append(seg)
                    assistant_parts.append({"text": part.text})
                    yield seg
                elif part.inline_data:
                    img_data = base64.b64encode(part.inline_data.data).decode()
                    seg = StorySegment(segment_type="image", content=img_data, mime_type=part.inline_data.mime_type or "image/png")
                    state.segments.append(seg)
                    assistant_parts.append({"text": "[illustration]"})
                    yield seg
            state.chat_history.append({"role": "model", "parts": assistant_parts})
        except Exception as e:
            async for seg in self._fallback( state, prompt):
                yield seg

    async def _fallback(self, state: StoryState, prompt: str):
        text_response = await self.client.aio.models.generate_content(
            model=FALLBACK_MODEL,
            contents=state.chat_history,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0.9,
                max_output_tokens=2048,
            ),
        )
        txt = text_response.text
        seg = StorySegment(segment_type="text", content=txt, mime_type="text/plain")
        state.segments.append(seg)
        state.chat_history.append({"role": "model", "parts": [{"text": txt}]})
        yield seg
        scene_prompt = f"Generate a cinematic illustration for: {txt[:500]} Style: {state.genre.value} genre."
        try:
            img_r = await self.client.aio.models.generate_content(
                model=GEMINI_MODEL,
                contents=[{"role": "user", "parts": [{"text": scene_prompt}]}],
                config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
            )
            for p in img_r.candidates[0].content.parts:
                if p.inline_data:
                    id = base64.b64encode(p.inline_data.data).decode()
                    s = StorySegment(segment_type="image", content=id, mime_type=p.inline_data.mime_type or "image/png")
                    state.segments.append(s)
                    yield s
        except:
            pass

    def _build_opening_prompt(self, state, user_input):
        return f"""Begin a new interactive {state.genre.value} story.
Premise: "{user_input}"
Create a captivating opening scene with an illustration. End with 2-3 choices."""

    def _build_continuation_prompt(self, state, user_input):
        return f"""The reader chose: {user_input}
Continue the story with consequences, an illustration, and 2-3 new choices."""

    async def generate_title(self, genre: StoryGenre, premise: str) -> str:
        r = await self.client.aio.models.generate_content(
            model=FALLBACK_MODEL,
            contents=[{"role": "user", "parts": [{"text": f"Generate a single compelling title for a {genre.value} story: {premise}. Reply with ONLY the title."}]}],
            config=types.GenerateContentConfig(temperature=1.0, max_output_tokens=50),
        )
        return r.text.strip().strip('"')
