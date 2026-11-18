"""Request models for the HTTP API.

Response payloads are assembled by the routers from deterministic analytics results and documented in
``docs/API.md``; only inputs are validated here, so an unexpected response field never blocks a request.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SaveCreate(BaseModel):
    """Body for creating a save."""

    name: str = Field(min_length=1, max_length=128)
    game_version: str | None = None
    game_build: str | None = None


class WatchItemCreate(BaseModel):
    """Add one player to the watchlist."""

    instance_id: int
    tag: str | None = None
    note: str | None = None


class WatchItemUpdate(BaseModel):
    """Change the tag or note of a watchlist entry."""

    tag: str | None = None
    note: str | None = None


class EvaluateRequest(BaseModel):
    """Score one player against one role template."""

    instance_id: int
    role_key: str


class ScoutingSearchRequest(BaseModel):
    """Role-aware scouting search."""

    save_id: int | None = None
    role_key: str | None = None
    query: str | None = None
    position: str | None = None
    position_group: str | None = None
    min_age: int | None = None
    max_age: int | None = None
    min_ca: int | None = None
    min_pa: int | None = None
    max_value: int | None = None
    max_wage: int | None = None
    club_id: int | None = None
    limit: int = Field(default=25, ge=1, le=200)


class ConversationCreate(BaseModel):
    """Create a decision conversation."""

    save_id: int | None = None
    title: str | None = Field(default=None, max_length=128)


class AskRequest(BaseModel):
    """Ask one question inside a conversation."""

    question: str = Field(min_length=2, max_length=2000)
    save_id: int | None = None
    instance_id: int | None = None
    club_id: int | None = None
