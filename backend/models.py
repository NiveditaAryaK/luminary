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

    def to_state(self) -> dict:
        """Full persistable state. Image payloads are returned under 'blobs'
        (keyed anchor/last/sb{turn}) so the store can chunk them separately —
        base64 images do not fit Firestore's 1 MiB document limit."""
        blobs: dict[str, dict] = {}
        storyboard_meta = []
        for beat in self.storyboard:
            blob_key = None
            if beat.image:
                blob_key = f"sb{beat.turn}"
                blobs[blob_key] = {"data": beat.image, "mime": beat.mime_type}
            storyboard_meta.append({
                "turn": beat.turn,
                "caption": beat.caption,
                "mime_type": beat.mime_type,
                "blob": blob_key,
            })
        if self.anchor_image:
            blobs["anchor"] = {"data": self.anchor_image, "mime": self.anchor_mime}
        if self.last_image:
            blobs["last"] = {"data": self.last_image, "mime": self.last_image_mime}
        return {
            "session_id": self.session_id,
            "title": self.title,
            "genre": self.genre,
            "premise": self.premise,
            "history": self.history,
            "turns": self.turns,
            "director_mode": self.director_mode,
            "style_bible": self.style_bible,
            "narration_pending": self.narration_pending,
            "memory": [{"label": item.label, "detail": item.detail} for item in self.memory],
            "storyboard": storyboard_meta,
            "blobs": blobs,
        }

    @classmethod
    def from_state(cls, state: dict) -> "StorySession":
        blobs = state.get("blobs") or {}

        def blob_data(key):
            return (blobs.get(key) or {}).get("data") if key else None

        return cls(
            genre=state.get("genre", ""),
            premise=state.get("premise", ""),
            title=state.get("title", ""),
            history=state.get("history") or [],
            turns=state.get("turns") or 0,
            director_mode=state.get("director_mode") or "cinematic",
            memory=[
                StoryMemory(label=item.get("label", "Story thread"), detail=item.get("detail", ""))
                for item in (state.get("memory") or [])
            ],
            storyboard=[
                StoryboardBeat(
                    turn=item.get("turn", 0),
                    caption=item.get("caption", ""),
                    image=blob_data(item.get("blob")),
                    mime_type=item.get("mime_type"),
                )
                for item in (state.get("storyboard") or [])
            ],
            session_id=state["session_id"],
            style_bible=state.get("style_bible") or "",
            anchor_image=blob_data("anchor"),
            anchor_mime=(blobs.get("anchor") or {}).get("mime"),
            last_image=blob_data("last"),
            last_image_mime=(blobs.get("last") or {}).get("mime"),
            narration_pending=state.get("narration_pending") or "",
        )

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
