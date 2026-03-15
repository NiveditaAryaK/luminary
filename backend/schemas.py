from pydantic import BaseModel


class CreateReq(BaseModel):
    genre: str
    premise: str
