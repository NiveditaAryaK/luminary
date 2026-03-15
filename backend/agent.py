from google.adk.agents import Agent
from story_engine import LuminaryEngine, StoryGenre
import os

engine = LuminaryEngine()
AGENT_MODEL = os.getenv("GEMINI_TITLE_MODEL", "gemini-2.5-flash")

def start_story(genre: str, premise: str) -> dict:
    """Start a new interactive story session."""
    try:
        g = StoryGenre(genre.lower())
    except ValueError:
        g = StoryGenre.FANTASY
    state = engine.create_session(g, premise)
    return {"session_id": state.session_id, "status": "started", "genre": genre}

def continue_story(session_id: str, choice: str) -> dict:
    """Continue the story with a player choice."""
    state = engine.get_session(session_id)
    if not state:
        return {"error": f"Session {session_id} not found"}
    return {"session_id": session_id, "choice": choice, "status": "continuing"}

def get_story_status(session_id: str) -> dict:
    """Get current story session status."""
    state = engine.get_session(session_id)
    if not state:
        return {"error": "Session not found"}
    return {"session_id": session_id, "genre": state.genre.value,
            "turn_count": state.turn_count, "segments": len(state.segments)}

def list_genres() -> dict:
    """List all available story genres."""
    return {"genres": [g.value for g in StoryGenre]}

root_agent = Agent(
    name="luminary_agent",
    model=AGENT_MODEL,
    description="Luminary cinematic AI storytelling agent",
    instruction="You are Luminary, a master cinematic storyteller. Help users create immersive interactive stories with vivid illustrations.",
    tools=[start_story, continue_story, get_story_status, list_genres],
)
