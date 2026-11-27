"""俱乐部解析：把「球员记录里的俱乐部信息」变成一条稳定的俱乐部记录。

为什么需要它：真实 FMSuperScout 导出**没有 clubs 数组、没有 clubId**（见 ``docs/FMSCOUT_FIELD_COVERAGE.md``），
只有球员行里的俱乐部名称。ScoutMind 不能因此把所有球员算成自己的队员，也不能把没有俱乐部的球员当成自由球员。

解析优先级（与产品规格一致）：

1. 报文里的俱乐部对象（``clubs[]``，带 uid）——最可信；
2. 球员记录里的俱乐部 uid / 名称（真实导出目前只给名称）；
3. 用户导入的阵容 CSV（见 :mod:`app.ingestion.squad_csv`）；
4. 用户手动指定的主执教俱乐部。

每条俱乐部记录都带 ``source`` 与 ``confidence``，界面必须展示它们；手动指定主执教俱乐部只写
``fm_saves.user_club_id``，**不移动任何球员**。
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import Club, FmSave, PlayerInstance, PlayerSnapshot

#: Provenance values shown in the UI. Confidence is a fixed property of the channel, not a guess.
SOURCE_PAYLOAD_CLUBS = "payload_clubs"
SOURCE_PLAYER_FIELD = "player_club_field"
SOURCE_CSV = "squad_csv"
SOURCE_MANUAL = "manual"

SOURCE_LABELS = {
    SOURCE_PAYLOAD_CLUBS: "扫描报文中的俱乐部对象",
    SOURCE_PLAYER_FIELD: "球员记录中的俱乐部名称",
    SOURCE_CSV: "阵容 CSV",
    SOURCE_MANUAL: "手动指定",
}

#: How much trust each channel deserves. A name-only club is weaker than an object with an id.
SOURCE_CONFIDENCE = {
    SOURCE_PAYLOAD_CLUBS: 1.0,
    SOURCE_PLAYER_FIELD: 0.6,
    SOURCE_CSV: 0.9,
    SOURCE_MANUAL: 1.0,
}

_NON_WORD = re.compile(r"[^0-9a-z\u4e00-\u9fff]+")
_SPACES = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    """Stable comparison key for club names: case, accents, punctuation and spacing folded away."""
    folded = unicodedata.normalize("NFKD", name)
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    folded = folded.lower().replace("&", " and ")
    folded = _NON_WORD.sub(" ", folded)
    return _SPACES.sub(" ", folded).strip()


def name_uid(normalized: str) -> str:
    """Deterministic uid for a name-only club, so repeated imports reuse the same row."""
    slug = _NON_WORD.sub("-", normalized).strip("-")
    return f"name:{slug}" if slug else "name:unknown"


@dataclass
class ResolvedClub:
    """Result of a resolve call, including where the row came from."""

    club: Club
    created: bool
    source: str
    confidence: float


class ClubResolver:
    """Creates, merges and upgrades club rows for one save."""

    def __init__(self, session: Session, save_id: int) -> None:
        self.session = session
        self.save_id = save_id
        self._by_uid: dict[str, Club] = {}
        self._by_name: dict[str, Club] = {}
        self._loaded = False

    # -- public ---------------------------------------------------------------------------------------------

    def resolve(
        self,
        *,
        uid: str | None = None,
        name: str | None = None,
        league: str | None = None,
        reputation: int | None = None,
        nation: str | None = None,
        source: str = SOURCE_PLAYER_FIELD,
        source_uid: str | None = None,
    ) -> ResolvedClub | None:
        """Find or create the club described by ``uid``/``name``.

        ``uid`` wins when both are present. A name-only club gets a deterministic ``name:<slug>`` uid so the same
        name never creates a second row; a later payload that carries a real uid upgrades that row instead of
        duplicating it.
        """
        self._ensure_loaded()
        if not uid and not name:
            return None
        normalized = normalize_name(name) if name else ""
        confidence = SOURCE_CONFIDENCE.get(source, 0.5)

        club = self._by_uid.get(uid) if uid else None
        if club is None and normalized:
            club = self._by_name.get(normalized)
        if club is None:
            club = self._create(
                uid=uid,
                name=name,
                normalized=normalized,
                source=source,
                confidence=confidence,
                league=league,
                nation=nation,
                reputation=reputation,
            )
            return ResolvedClub(club=club, created=True, source=source, confidence=confidence)

        self._enrich(club, name=name, league=league, reputation=reputation, nation=nation)
        self._upgrade(club, uid=uid, name=name, normalized=normalized, source=source, confidence=confidence,
                      source_uid=source_uid)
        return ResolvedClub(club=club, created=False, source=club.source or source,
                            confidence=club.confidence if club.confidence is not None else confidence)

    def search(self, query: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """Clubs of this save with member counts, for the operator's club picker."""
        self._ensure_loaded()
        statement = select(Club).where(Club.fm_save_id == self.save_id).order_by(Club.name)
        if query:
            needle = f"%{query.strip()}%"
            statement = statement.where(Club.name.ilike(needle))
        rows = list(self.session.scalars(statement.limit(limit)))
        counts = self._member_counts([club.id for club in rows])
        save = self.session.get(FmSave, self.save_id)
        return [
            {
                "id": club.id,
                "uid": club.uid,
                "name": club.name,
                "nation": club.nation,
                "league": club.league,
                "reputation": club.reputation,
                "is_user_club": bool(save and save.user_club_id == club.id),
                "source": club.source,
                "source_label": SOURCE_LABELS.get(club.source or "", club.source),
                "confidence": club.confidence,
                "players": counts.get(club.id, 0),
            }
            for club in rows
        ]

    def set_user_club(self, club_id: int, source: str = SOURCE_MANUAL) -> Club:
        """Point the save at its managed club. Never touches ``player_instances.club_id``."""
        club = self.session.get(Club, club_id)
        if club is None or club.fm_save_id != self.save_id:
            raise ValueError("俱乐部不存在")
        save = self.session.get(FmSave, self.save_id)
        if save is None:
            raise ValueError("存档不存在")
        save.user_club_id = club.id
        save.user_club_source = source
        # is_user_club 只是派生标记，供旧查询与导出使用；唯一事实来源是 fm_saves.user_club_id。
        for other in self.session.scalars(select(Club).where(Club.fm_save_id == self.save_id)):
            other.is_user_club = other.id == club.id
        self.session.flush()
        return club

    def clear_user_club(self) -> None:
        save = self.session.get(FmSave, self.save_id)
        if save is not None:
            save.user_club_id = None
            save.user_club_source = None
        for other in self.session.scalars(select(Club).where(Club.fm_save_id == self.save_id)):
            other.is_user_club = False
        self.session.flush()

    def user_club(self) -> Club | None:
        """Managed club: explicit save pointer first, then the legacy flag."""
        save = self.session.get(FmSave, self.save_id)
        if save is not None and save.user_club_id is not None:
            club = self.session.get(Club, save.user_club_id)
            if club is not None:
                return club
        return self.session.scalar(
            select(Club)
            .where(Club.fm_save_id == self.save_id, Club.is_user_club.is_(True))
            .order_by(Club.id)
            .limit(1)
        )

    # -- internals ------------------------------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        for club in self.session.scalars(select(Club).where(Club.fm_save_id == self.save_id)):
            self._by_uid[club.uid] = club
            if club.normalized_name:
                self._by_name.setdefault(club.normalized_name, club)
        self._loaded = True

    def _create(
        self,
        *,
        uid: str | None,
        name: str | None,
        normalized: str,
        source: str,
        confidence: float,
        league: str | None = None,
        nation: str | None = None,
        reputation: int | None = None,
    ) -> Club:
        resolved_uid = uid or name_uid(normalized)
        # 缓存可能落后于数据库（同一事务里刚插入、或另一个 resolver 已建），先确认一次再插入。
        existing = self._by_uid.get(resolved_uid)
        if existing is None:
            existing = self.session.scalar(
                select(Club).where(Club.fm_save_id == self.save_id, Club.uid == resolved_uid)
            )
        if existing is not None:
            self._by_uid[resolved_uid] = existing
            if existing.normalized_name:
                self._by_name.setdefault(existing.normalized_name, existing)
            return existing

        # 只有 uid、没有名称时：name:<slug> 形式的 uid 可以反推出归一化名称，让之后按名称解析能命中同一行。
        derived = ""
        if not normalized and resolved_uid.startswith("name:"):
            derived = resolved_uid[len("name:") :].replace("-", " ")
            normalized = normalize_name(derived)
        display = name or (derived or resolved_uid)
        club = Club(
            fm_save_id=self.save_id,
            uid=resolved_uid,
            name=display,
            normalized_name=normalized or None,
            source=source,
            confidence=confidence,
            # 首次创建时也要保留扫描提供的联赛/国家/声望，否则「所属联赛（有数据时）」永远为空。
            league=league,
            nation=nation,
            reputation=reputation,
        )
        try:
            # 并发导入可能同时创建同一 (save, uid)：唯一约束先到先得，后到者复读已有行。
            with self.session.begin_nested():
                self.session.add(club)
                self.session.flush()
        except IntegrityError:
            existing = self.session.scalar(
                select(Club).where(Club.fm_save_id == self.save_id, Club.uid == resolved_uid)
            )
            if existing is None:
                raise
            self._by_uid[resolved_uid] = existing
            if existing.normalized_name:
                self._by_name.setdefault(existing.normalized_name, existing)
            return existing
        self._by_uid[resolved_uid] = club
        if normalized:
            self._by_name.setdefault(normalized, club)
        return club
    def _enrich(
        self,
        club: Club,
        *,
        name: str | None,
        league: str | None,
        reputation: int | None,
        nation: str | None,
    ) -> None:
        """Fill blanks only: an observed value is never overwritten by a later, weaker channel."""
        if name and (not club.name or club.name.startswith("name:")):
            club.name = name
        if league and not club.league:
            club.league = league
        if reputation is not None and club.reputation is None:
            club.reputation = reputation
        if nation and not club.nation:
            club.nation = nation
        if name and not club.normalized_name:
            club.normalized_name = normalize_name(name)

    def _upgrade(
        self,
        club: Club,
        *,
        uid: str | None,
        name: str | None,
        normalized: str,
        source: str,
        confidence: float,
        source_uid: str | None,
    ) -> None:
        """Promote a name-derived row when a real uid arrives; record the external id either way."""
        external = json.loads(club.external_ids_json or "{}")
        if source_uid:
            external[source] = source_uid
        if uid and club.uid != uid:
            taken = self._by_uid.get(uid)
            if taken is None or taken.id == club.id:
                self._by_uid.pop(club.uid, None)
                club.uid = uid
                self._by_uid[uid] = club
                external.setdefault(source, uid)
                if confidence >= (club.confidence or 0):
                    club.source = source
                    club.confidence = confidence
        if name and not club.normalized_name:
            club.normalized_name = normalize_name(name)
            self._by_name.setdefault(club.normalized_name, club)
        if source_uid:
            club.external_ids_json = json.dumps(external, ensure_ascii=False)

    def _member_counts(self, club_ids: list[int]) -> dict[int, int]:
        if not club_ids:
            return {}
        rows = self.session.execute(
            select(PlayerSnapshot.club_id, func.count())
            .join(PlayerInstance, PlayerInstance.id == PlayerSnapshot.player_instance_id)
            .where(
                PlayerInstance.fm_save_id == self.save_id,
                PlayerSnapshot.club_id.in_(club_ids),
            )
            .group_by(PlayerSnapshot.club_id)
        ).all()
        return {int(club_id): int(count) for club_id, count in rows if club_id is not None}
