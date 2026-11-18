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


class SquadWeights(BaseModel):
    """Per-request override of the six squad-score weights; unset components keep the profile value."""

    coverage: float | None = Field(default=None, ge=0, le=1)
    depth: float | None = Field(default=None, ge=0, le=1)
    age: float | None = Field(default=None, ge=0, le=1)
    fit: float | None = Field(default=None, ge=0, le=1)
    wage: float | None = Field(default=None, ge=0, le=1)
    potential: float | None = Field(default=None, ge=0, le=1)

    def overrides(self) -> dict[str, float]:
        """Only the components the caller actually sent."""
        return {key: value for key, value in self.model_dump().items() if value is not None}


class TacticalProfileUpdate(BaseModel):
    """Create or replace one weight profile of a save."""

    key: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=256)
    weights: SquadWeights = Field(default_factory=SquadWeights)
    is_default: bool = False


class RecruitmentSearchRequest(BaseModel):
    """Filters for the recruitment engine."""

    save_id: int | None = None
    slot: str | None = None
    min_age: int | None = Field(default=None, ge=10, le=60)
    max_age: int | None = Field(default=None, ge=10, le=60)
    max_value: int | None = Field(default=None, ge=0)
    max_wage: int | None = Field(default=None, ge=0)
    min_score: float | None = Field(default=None, ge=0, le=100)
    exclude_own_club: bool = True
    limit: int = Field(default=25, ge=1, le=200)


class ShortlistRequest(BaseModel):
    """Generate and store a shortlist."""

    save_id: int | None = None
    name: str = Field(min_length=1, max_length=128)
    slot: str | None = None
    role_key: str | None = None
    budget: int | None = Field(default=None, ge=0)
    min_age: int | None = Field(default=None, ge=10, le=60)
    max_age: int | None = Field(default=None, ge=10, le=60)
    limit: int = Field(default=10, ge=1, le=50)
    persist: bool = True


class CompareRequest(BaseModel):
    """Compare several players with the same scoring weights."""

    save_id: int | None = None
    instance_ids: list[int] = Field(min_length=2, max_length=5)


class DealRequest(BaseModel):
    """Deal model inputs for one prospective signing."""

    save_id: int | None = None
    instance_id: int
    fee: float | None = Field(default=None, ge=0)
    budget: int | None = Field(default=None, ge=0)
    wage_period: str = Field(default="week", pattern="^(week|month|year)$")
    contract_years: float | None = Field(default=None, gt=0, le=20)
