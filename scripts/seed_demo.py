"""Generate a clearly-labelled synthetic demo dataset and import it.

The dataset exists so the UI and the analytics can be exercised before a real FM27 scan is available. Every record
carries ``source="synthetic_fixture"`` and the API reports ``demo_mode=true``; it must never be presented as real
game data. Real imports use the same protocol, so this script doubles as an end-to-end fixture generator.

Usage:
    python scripts/seed_demo.py            # write samples/demo/*.json and import them
    python scripts/seed_demo.py --force    # delete the demo save first
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.config import settings  # noqa: E402
from app.db import SessionLocal, schema_ready  # noqa: E402
from app.ingestion.importer import ScanImporter  # noqa: E402
from app.ingestion.protocol import ScanPayload  # noqa: E402
from app.models import (  # noqa: E402
    AgentConversation,
    AgentMessage,
    AiReport,
    Alert,
    Club,
    DataSource,
    FmSave,
    IdentityMatch,
    ImportJob,
    ImportRow,
    PlayerAttributeValue,
    Player,
    PlayerInstance,
    PlayerScore,
    PlayerSnapshot,
    PlayerStatistic,
    PlayerValuation,
    RecruitmentShortlist,
    RecruitmentShortlistItem,
    ScoutingReport,
    TacticalProfile,
    Transfer,
    TransferFeeComponent,
    User,
    Watchlist,
    WatchlistItem,
)
from sqlalchemy import delete, func, select  # noqa: E402


def _purge_save(session, save_id: int) -> None:
    """Delete every row that belongs to one demo save, respecting foreign keys."""
    instance_ids = list(session.scalars(select(PlayerInstance.id).where(PlayerInstance.fm_save_id == save_id)))
    snapshot_ids = (
        list(session.scalars(select(PlayerSnapshot.id).where(PlayerSnapshot.player_instance_id.in_(instance_ids))))
        if instance_ids
        else []
    )
    transfer_ids = list(session.scalars(select(Transfer.id).where(Transfer.fm_save_id == save_id)))
    watch_ids = list(session.scalars(select(Watchlist.id).where(Watchlist.fm_save_id == save_id)))
    job_ids = list(session.scalars(select(ImportJob.id).where(ImportJob.fm_save_id == save_id)))
    if transfer_ids:
        session.execute(delete(TransferFeeComponent).where(TransferFeeComponent.transfer_id.in_(transfer_ids)))
    session.execute(delete(Transfer).where(Transfer.fm_save_id == save_id))
    shortlist_ids = list(
        session.scalars(select(RecruitmentShortlist.id).where(RecruitmentShortlist.fm_save_id == save_id))
    )
    if shortlist_ids:
        session.execute(
            delete(RecruitmentShortlistItem).where(RecruitmentShortlistItem.shortlist_id.in_(shortlist_ids))
        )
        session.execute(delete(RecruitmentShortlist).where(RecruitmentShortlist.id.in_(shortlist_ids)))
    session.execute(delete(ScoutingReport).where(ScoutingReport.fm_save_id == save_id))
    session.execute(delete(AiReport).where(AiReport.fm_save_id == save_id))
    session.execute(delete(TacticalProfile).where(TacticalProfile.fm_save_id == save_id))
    if instance_ids:
        session.execute(delete(PlayerStatistic).where(PlayerStatistic.player_instance_id.in_(instance_ids)))
        session.execute(delete(PlayerAttributeValue).where(PlayerAttributeValue.player_snapshot_id.in_(snapshot_ids)))
    if instance_ids:
        session.execute(delete(PlayerSnapshot).where(PlayerSnapshot.player_instance_id.in_(instance_ids)))
        session.execute(delete(PlayerValuation).where(PlayerValuation.player_instance_id.in_(instance_ids)))
        session.execute(delete(PlayerScore).where(PlayerScore.player_instance_id.in_(instance_ids)))
        session.execute(delete(WatchlistItem).where(WatchlistItem.player_instance_id.in_(instance_ids)))
        session.execute(delete(Alert).where(Alert.player_instance_id.in_(instance_ids)))
    if watch_ids:
        session.execute(delete(WatchlistItem).where(WatchlistItem.watchlist_id.in_(watch_ids)))
        session.execute(delete(Watchlist).where(Watchlist.id.in_(watch_ids)))
    session.execute(delete(Alert).where(Alert.fm_save_id == save_id))
    if instance_ids:
        session.execute(delete(PlayerInstance).where(PlayerInstance.id.in_(instance_ids)))
    if job_ids:
        session.execute(delete(ImportRow).where(ImportRow.import_job_id.in_(job_ids)))
    session.execute(delete(ImportJob).where(ImportJob.fm_save_id == save_id))
    conversation_ids = list(
        session.scalars(select(AgentConversation.id).where(AgentConversation.fm_save_id == save_id))
    )
    if conversation_ids:
        session.execute(delete(AgentMessage).where(AgentMessage.conversation_id.in_(conversation_ids)))
        session.execute(delete(AgentConversation).where(AgentConversation.id.in_(conversation_ids)))
    session.execute(delete(DataSource).where(DataSource.fm_save_id == save_id))
    session.execute(delete(Club).where(Club.fm_save_id == save_id))
    session.execute(delete(IdentityMatch).where(IdentityMatch.fm_save_id == save_id))
    session.commit()
    # Identity rows are only meaningful through an instance; drop the ones this save left behind.
    session.execute(
        delete(Player).where(
            Player.id.not_in(select(PlayerInstance.player_id)),
            Player.id.not_in(select(IdentityMatch.player_id)),
        )
    )
    session.commit()

SOURCES = ("Northbridge United", "Kingsport City", "Ravensfield FC", "Ashcombe Rovers", "Port Vale Athletic",
           "Silverlake Town", "Hartsmere FC", "Dunmore Wanderers", "Eastcliff Sporting", "Welton Park",
           "Grange Hill FC", "Marston Rovers", "Brackenhill", "Fairhaven United")
LEAGUES = ("Premier Division", "Championship", "League One")

FIRST_NAMES = ("Adam", "Ben", "Callum", "Diego", "Elias", "Felix", "Gabriel", "Hugo", "Ivan", "Jonas", "Kai", "Luca",
               "Mateo", "Noah", "Oscar", "Pedro", "Rafael", "Samuel", "Theo", "Victor", "William", "Yusuf", "Zane",
               "Andre", "Bruno", "Carlos", "Dmitri", "Emre", "Franco", "Gustav")
LAST_NAMES = ("Almeida", "Bennett", "Costa", "Doyle", "Eriksen", "Fischer", "Gomes", "Hansen", "Iversen", "Jensen",
              "Kovac", "Lindqvist", "Moreau", "Novak", "Olsen", "Pereira", "Quinn", "Rossi", "Silva", "Tavares",
              "Ueda", "Vargas", "Walsh", "Xavier", "Young", "Zielinski", "Bakker", "Dahl", "Ferreira", "Garcia")

POSITIONS = ("GK", "DC", "DL", "DR", "DM", "MC", "AMC", "AML", "AMR", "ST")

#: The managed club gets a deliberately complete squad so the squad screen has every slot populated.
USER_SQUAD_PLAN: tuple[tuple[str, int], ...] = (
    ("GK", 3),
    ("DC", 4),
    ("DL", 2),
    ("DR", 2),
    ("DM", 2),
    ("MC", 3),
    ("AMC", 2),
    ("AML", 3),
    ("AMR", 2),
    ("ST", 3),
)

#: Season labels used by the generated statistics blocks, oldest first.
SEASON_PERIODS = ("2025/26", "2026/27")

ATTRIBUTE_POOL = {
    "GK": ("reflexes", "handling", "one_on_ones", "aerial_reach", "command_of_area", "communication", "kicking",
           "rushing_out", "positioning", "composure"),
    "DF": ("tackling", "marking", "positioning", "heading", "strength", "composure", "passing", "anticipation",
           "pace", "jumping", "bravery", "concentration"),
    "MF": ("passing", "vision", "technique", "decisions", "composure", "teamwork", "stamina", "first_touch",
           "off_the_ball", "work_rate", "anticipation", "long_shots"),
    "FW": ("finishing", "dribbling", "acceleration", "pace", "technique", "off_the_ball", "composure", "agility",
           "heading", "flair", "first_touch", "strength"),
}

CLUB_PROFILES = {
    "Premier Division": (7000, 9200),
    "Championship": (5000, 6800),
    "League One": (3800, 4800),
}


def _group_of(position: str) -> str:
    if position == "GK":
        return "GK"
    if position in {"DC", "DL", "DR"}:
        return "DF"
    if position in {"DM", "MC", "AMC"}:
        return "MF"
    return "FW"


def _new_player(rng: random.Random, index: int, position: str, club: dict, used_names: set[str]) -> dict:
    """One synthetic player with a stable UID, attribute set and value band."""
    while True:
        name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
        if name not in used_names:
            used_names.add(name)
            break
    birth_year = rng.randint(1993, 2010)
    pa = rng.randint(110, 195)
    age_2026 = 2026 - birth_year
    ca = max(min(pa - rng.randint(0, 25), 190), 85) if age_2026 < 24 else rng.randint(110, 160)
    return {
        "uid": f"P{1000 + index}",
        "name": name,
        "position": position,
        "birth_date": date(birth_year, rng.randint(1, 12), rng.randint(1, 28)).isoformat(),
        "nationality": rng.choice(("England", "Spain", "Brazil", "France", "Germany", "Italy", "Portugal",
                                  "Netherlands", "Argentina", "Japan")),
        "club_uid": club["uid"],
        "ca": ca,
        "pa": pa,
        "attributes": {key: rng.randint(8, 18) for key in ATTRIBUTE_POOL[_group_of(position)]},
        "wage": rng.randint(4_000, 120_000),
        "contract_end": date(2027 + rng.randint(0, 4), rng.randint(1, 12), 28).isoformat(),
        "value_base": rng.randint(800_000, 60_000_000),
        # 状态字段：让挂牌/伤病/租借在演示数据里也有真实取值，界面与接口才有东西可展示。
        "availability": {
            "listed": rng.random() < 0.18,
            "loan_listed": rng.random() < 0.05,
            "not_for_sale": rng.random() < 0.12,
            "set_for_release": rng.random() < 0.04,
            "injury_proneness": rng.randint(4, 18),
            "injured": rng.random() < 0.12,
            "injury_start_date": None,
            "expected_return_date": None,
            "injury_note": None,
        },
        "ownership": None,
        "agreed_transfer": None,
    }


def _availability_for(player: dict, scan_index: int) -> dict:
    """Availability block for one scan; listing flips for some players so the timeline has real changes."""
    base = dict(player.get("availability") or {})
    if not base:
        base = {"listed": False, "injury_proneness": 10, "injured": False}
    listed = bool(base.get("listed"))
    # 每一轮扫描让约 1/4 的球员改变挂牌状态，形成可观测的变化。
    if scan_index == 1 and (int(player["uid"][1:]) % 4 == 0):  # 用 UID 的稳定模数，保证演示数据可复现
        listed = not listed
    return {
        "listed": listed,
        "loan_listed": base.get("loan_listed"),
        "not_for_sale": base.get("not_for_sale"),
        "set_for_release": base.get("set_for_release"),
        "injury_proneness": base.get("injury_proneness"),
        "injured": base.get("injured"),
        "injury_start_date": None,
        "expected_return_date": None,
        "injury_note": None,
    }


def build_players(rng: random.Random, clubs: list[dict]) -> list[dict]:
    """Create a stable player pool; later scans reuse the same UIDs."""
    players: list[dict] = []
    used_names: set[str] = set()
    index = 0
    for position, count in USER_SQUAD_PLAN:
        for _ in range(count):
            players.append(_new_player(rng, index, position, clubs[0], used_names))
            index += 1
    for _ in range(66):
        players.append(_new_player(rng, index, POSITIONS[index % len(POSITIONS)], clubs[1 + index % (len(clubs) - 1)],
                                   used_names))
        index += 1
    _add_loan_and_pending_move(players, clubs)
    return players


def _add_loan_and_pending_move(players: list[dict], clubs: list[dict]) -> None:
    """Give the demo pool one real loan and one agreed-but-not-yet-registered move.

    Both are deterministic: the loan keeps the owner club and the agreed move stays out of every spending total.
    """
    parent_uid = clubs[3]["uid"]
    loan_club_uid = clubs[2]["uid"]
    loaned = next((item for item in players if item["club_uid"] == parent_uid), None)
    if loaned is not None:
        loaned["ownership"] = {
            "parent_club_uid": parent_uid,
            "loan_club_uid": loan_club_uid,
            "team_type": "senior",
            "loan_start_date": None,
            "loan_end_date": None,
            "has_option": None,
            "has_obligation": None,
        }
        loaned["club_uid"] = loan_club_uid
    buyer_uid = clubs[1]["uid"]
    pending = next((item for item in players if item["club_uid"] == buyer_uid), None)
    if pending is not None:
        pending["agreed_transfer"] = {"to_club_uid": clubs[0]["uid"], "transfer_date": "2027-07-01"}


def build_statistics(rng: random.Random, player: dict, period_index: int) -> dict:
    """Season aggregate block shaped like a real scouting export, scaled by ability and position."""
    group = _group_of(player["position"])
    ability = max(60, min(190, player["ca"] - (5 if period_index == 0 else 0)))
    appearances = max(4, min(38, int((ability - 60) / 3) + rng.randint(-4, 6)))
    minutes = max(120, appearances * rng.randint(55, 88))
    games_per90 = minutes / 90
    stats: dict[str, object] = {
        "period": SEASON_PERIODS[period_index],
        "competition": "Premier Division",
        "appearances": appearances,
        "starts": max(0, appearances - rng.randint(0, 6)),
        "minutes_played": minutes,
    }
    if group == "FW":
        goals = max(0, int(games_per90 * (ability - 95) / 55) + rng.randint(-2, 3))
        stats.update(
            goals=goals,
            assists=max(0, int(goals * rng.uniform(0.2, 0.7))),
            shots=max(goals, int(games_per90 * rng.uniform(0.6, 3.2))),
            shots_on_target=max(goals, int(games_per90 * rng.uniform(0.3, 1.4))),
            xg=round(games_per90 * rng.uniform(0.1, 0.7), 2),
        )
    elif group == "MF":
        stats.update(
            assists=max(0, int(games_per90 * rng.uniform(0.05, 0.35))),
            key_passes=max(0, int(games_per90 * rng.uniform(0.4, 2.4))),
            tackles=max(0, int(games_per90 * rng.uniform(0.6, 3.4))),
            passes_attempted=max(1, int(games_per90 * rng.uniform(28, 72))),
        )
        stats["passes_completed"] = int(stats["passes_attempted"] * rng.uniform(0.72, 0.93))  # type: ignore[arg-type]
    elif group == "DF":
        stats.update(
            tackles=max(0, int(games_per90 * rng.uniform(0.8, 3.6))),
            interceptions=max(0, int(games_per90 * rng.uniform(0.6, 3.0))),
            clearances=max(0, int(games_per90 * rng.uniform(1.0, 5.0))),
            aerials_won=max(0, int(games_per90 * rng.uniform(0.5, 3.5))),
        )
    else:
        stats.update(
            saves=max(0, int(games_per90 * rng.uniform(1.4, 4.2))),
            conceded=max(0, int(games_per90 * rng.uniform(0.6, 2.2))),
            clean_sheets=max(0, int(appearances * rng.uniform(0.1, 0.45))),
        )
    return stats


def build_scan(
    scan_index: int,
    game_date: date,
    players: list[dict],
    clubs: list[dict],
    transfers: list[dict],
    rng: random.Random,
) -> dict:
    """Build one scan document at a given game date."""
    rows: list[dict] = []
    for player in players:
        age = game_date.year - date.fromisoformat(player["birth_date"]).year
        growth = 0 if age >= 24 else min(scan_index * 2, 6)
        value = int(player["value_base"] * (1 + 0.18 * scan_index + rng.uniform(-0.04, 0.04)))
        attributes = dict(player["attributes"])
        if age < 24:
            for key in attributes:
                attributes[key] = min(20, attributes[key] + (1 if scan_index and rng.random() < 0.35 else 0))
        rows.append(
            {
                "record_id": player["uid"],
                "save_local_uid": player["uid"],
                "game_unique_id": f"G{player['uid']}",
                "name": player["name"],
                "birth_date": player["birth_date"],
                "nationality": player["nationality"],
                "position": player["position"],
                "club_uid": player["club_uid"],
                "ca": min(player["ca"] + growth, player["pa"]),
                "pa": player["pa"],
                "market_value": value,
                "wage": player["wage"],
                "contract_end": player["contract_end"],
                "appearances": scan_index * 11 + rng.randint(0, 4),
                "minutes_played": scan_index * 900 + rng.randint(0, 180),
                "goals": scan_index * 2 + rng.randint(0, 3),
                "assists": scan_index + rng.randint(0, 2),
                "attributes": attributes,
                # 挂牌状态随扫描推进偶尔变化，用来验证「状态变化」与「首次发现」。
                "availability": _availability_for(player, scan_index),
                "ownership": player.get("ownership"),
                "agreed_transfer": player.get("agreed_transfer"),
                "statistics": [build_statistics(rng, player, period_index) for period_index in (0, 1)],
            }
        )
    return {
        "schema_version": "1.0",
        "source": "synthetic_fixture",
        "reader_version": "demo-1",
        "game": {"version": "27.0.0-demo", "build": "synthetic", "app_id": "demo"},
        "scan": {
            "scan_id": f"demo-scan-{scan_index + 1:02d}",
            "observed_at": datetime(game_date.year, game_date.month, game_date.day, 12, tzinfo=timezone.utc).isoformat(),
            "game_date": game_date.isoformat(),
            "user_club_uid": clubs[0]["uid"],
        },
        "coverage": {"players": True, "transfers": scan_index == 0, "attributes": True, "finances": False},
        "warnings": ["演示数据：由 seed_demo.py 生成，不是 FM27 真实读取结果"],
        "clubs": clubs,
        "players": rows,
        "transfers": transfers if scan_index == 0 else [],
    }


def build_transfers(rng: random.Random, players: list[dict], clubs: list[dict]) -> list[dict]:
    """Create completed, pending and cancelled transfers with fee components."""
    transfers: list[dict] = []
    for index in range(150):
        player = rng.choice(players)
        from_club, to_club = rng.sample(clubs, 2)
        transfer_date = date(2024, 1, 1) + timedelta(days=rng.randint(0, 1150))
        age = transfer_date.year - date.fromisoformat(player["birth_date"]).year
        ca = max(player["ca"] - rng.randint(0, 8), 70)
        fee = int(rng.uniform(500_000, 85_000_000) * (1 + max(0, 24 - age) / 30))
        status = "completed"
        transfer_type = "permanent"
        if index % 17 == 0:
            status = "pending"
        elif index % 29 == 0:
            status = "cancelled"
        elif index % 11 == 0:
            transfer_type = "loan"
            fee = int(fee * 0.08)
        elif index % 23 == 0:
            transfer_type = "free"
            fee = 0
        components: list[dict] = []
        if status == "completed" and transfer_type == "permanent":
            components.append({"type": "base_fee", "amount": fee * 0.8, "status": "paid"})
            components.append({"type": "installment", "amount": fee * 0.2, "status": "scheduled",
                               "due_date": (transfer_date + timedelta(days=365)).isoformat()})
            if index % 5 == 0:
                components.append({"type": "addon", "amount": fee * 0.15, "status": "untriggered",
                                   "condition": "出场 50 次"})
        transfers.append(
            {
                "record_id": f"T{5000 + index}",
                "player_record_id": player["uid"],
                "player_name": player["name"],
                "transfer_type": transfer_type,
                "status": status,
                "transfer_date": transfer_date.isoformat(),
                "season": f"{transfer_date.year}/{str(transfer_date.year + 1)[-2:]}",
                "from_club_uid": from_club["uid"],
                "from_club_name": from_club["name"],
                "to_club_uid": to_club["uid"],
                "to_club_name": to_club["name"],
                "currency": "EUR",
                "base_fee": fee,
                "fee_paid": fee if status == "completed" else None,
                "addons_potential": fee * 0.15 if index % 5 == 0 else None,
                "player_age_at_transfer": age,
                "player_ca_at_transfer": ca,
                "player_pa_at_transfer": player["pa"],
                "contract_remaining_months": rng.choice((6, 12, 18, 24, 30, 36)),
                "confidence": 1.0,
                "fee_components": components,
            }
        )
    return transfers


def build_clubs(rng: random.Random) -> list[dict]:
    """Clubs with league-dependent reputation."""
    clubs: list[dict] = []
    for index, name in enumerate(SOURCES):
        league = LEAGUES[min(index // 5, len(LEAGUES) - 1)]
        low, high = CLUB_PROFILES[league]
        clubs.append(
            {
                "uid": f"C{100 + index}",
                "name": name,
                "nation": "England",
                "league": league,
                "reputation": rng.randint(low, high),
                "is_user_club": index == 0,
            }
        )
    return clubs


def seed(force: bool, out_dir: Path) -> None:
    """Generate the sample scans, import them and print a summary."""
    settings.ensure_directories()
    if not schema_ready():
        raise SystemExit("数据库尚未迁移：请先在 backend 目录执行 alembic upgrade head")
    rng = random.Random(42)
    clubs = build_clubs(rng)
    players = build_players(rng, clubs)
    transfers = build_transfers(rng, players, clubs)
    out_dir.mkdir(parents=True, exist_ok=True)
    session = SessionLocal()
    try:
        user = session.scalar(select(User).where(User.username == "local"))
        if user is None:
            user = User(username="local", display_name="本地用户")
            session.add(user)
            session.commit()
        save = session.scalar(select(FmSave).where(FmSave.user_id == user.id, FmSave.name == "演示存档"))
        if save is not None and force:
            _purge_save(session, save.id)
            session.delete(save)
            session.commit()
            save = None
        if save is None:
            save = FmSave(user_id=user.id, name="演示存档", game_version="27.0-demo", game_build="synthetic", is_active=True)
            session.add(save)
            session.commit()
        importer = ScanImporter(session)
        for scan_index, game_date in enumerate((date(2026, 8, 1), date(2026, 11, 15), date(2027, 3, 1))):
            document = build_scan(scan_index, game_date, players, clubs, transfers, rng)
            path = out_dir / f"scan-{scan_index + 1:02d}.json"
            raw = json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8")
            path.write_bytes(raw)
            payload = ScanPayload.model_validate(document)
            outcome = importer.import_payload(save.id, payload, raw)
            print(
                f"{path.name}: status={outcome.status} snapshots={outcome.snapshots_created} "
                f"transfers={outcome.transfers_created} rejected={outcome.rows_rejected}"
            )
        players_count = session.scalar(select(func.count()).select_from(PlayerInstance).where(PlayerInstance.fm_save_id == save.id))
        transfers_count = session.scalar(select(func.count()).select_from(Transfer).where(Transfer.fm_save_id == save.id))
        print(f"演示存档 id={save.id}：球员实例 {players_count}，交易 {transfers_count}")
        print("提醒：所有记录 source=synthetic_fixture，不可用于真实决策。")
    finally:
        session.close()


def main() -> None:
    """Command line entry point."""
    parser = argparse.ArgumentParser(description="生成并导入 ScoutMind 演示数据")
    parser.add_argument("--force", action="store_true", help="删除已有演示存档后重建")
    parser.add_argument("--out-dir", default=str(ROOT / "samples" / "demo"), help="扫描样本输出目录")
    args = parser.parse_args()
    seed(args.force, Path(args.out_dir))


if __name__ == "__main__":
    main()



