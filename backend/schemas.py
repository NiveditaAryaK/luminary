from pydantic import BaseModel, Field


class CreateReq(BaseModel):
    genre: str
    premise: str
    director_mode: str = "cinematic"


class RestoreReq(BaseModel):
    title: str
    genre: str
    premise: str
    history: list[dict]
    turns: int = 0
    director_mode: str = "cinematic"
    memory: list[dict] = Field(default_factory=list)
    storyboard: list[dict] = Field(default_factory=list)
    style_bible: str = ""


class NarrationReq(BaseModel):
    text: str
    genre: str = "fantasy"
    voice_name: str | None = None
    language_code: str | None = None
