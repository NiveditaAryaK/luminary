from dataclasses import dataclass, field
import uuid


@dataclass
class StoryEvent:
    type: str
    content: str
    mime_type: str | None = None


@dataclass
class StorySession:
    genre: str
    premise: str
    title: str
    history: list[dict] = field(default_factory=list)
    turns: int = 0
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def snapshot(self) -> dict:
        return {
            "session_id": self.session_id,
            "title": self.title,
            "genre": self.genre,
            "premise": self.premise,
            "history": self.history,
            "turns": self.turns,
        }
