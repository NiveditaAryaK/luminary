import asyncio
import uuid
from dataclasses import dataclass, field


@dataclass
class StoryEvent:
    type: str
    content: str
    mime_type: str | None = None


@dataclass
class StoryMemory:
    label: str
    detail: str


@dataclass
class StoryboardBeat:
    turn: int
    caption: str
    image: str | None = None
    mime_type: str | None = None


@dataclass
class StorySession:
    genre: str
    premise: str
    title: str
    history: list[dict] = field(default_factory=list)
    turns: int = 0
    director_mode: str = "cinematic"
    memory: list[StoryMemory] = field(default_factory=list)
    storyboard: list[StoryboardBeat] = field(default_factory=list)
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    style_bible: str = ""
    anchor_image: str | None = None
    anchor_mime: str | None = None
    last_image: str | None = None
    last_image_mime: str | None = None
    narration_pending: str = ""
    narration_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False, compare=False)

    def snapshot(self) -> dict:
        return {
            "session_id": self.session_id,
            "title": self.title,
            "genre": self.genre,
            "premise": self.premise,
            "history": self.history,
            "turns": self.turns,
            "director_mode": self.director_mode,
            "style_bible": self.style_bible,
            "memory": [{"label": item.label, "detail": item.detail} for item in self.memory],
            "storyboard": [
                {
                    "turn": beat.turn,
                    "caption": beat.caption,
                    "image": beat.image,
                    "mime_type": beat.mime_type,
                }
                for beat in self.storyboard
            ],
        }
