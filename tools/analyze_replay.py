"""Decode `.replay26` files and summarize match behavior.

The analyzer is deliberately focused on strategy work rather than full replay
visualisation. It extracts enough structure to answer questions like:

- did we lose on macro or timing?
- were builders repeatedly stalling in place?
- what mix of buildings did each side actually place?
- which ladder maps trigger the worst no-progress patterns?
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import urllib.request
from collections import Counter, defaultdict, deque
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _add_cambc_site_packages() -> None:
    pyenv = shutil.which("pyenv")
    if pyenv is None:
        return
    result = subprocess.run(
        [pyenv, "prefix", "cambc"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return
    prefix = Path(result.stdout.strip())
    if not prefix.exists():
        return
    for site_packages in sorted((prefix / "lib").glob("python*/site-packages")):
        if site_packages.is_dir():
            sys.path.insert(0, str(site_packages))
            return


try:
    from cambc.api import api_get
    from cambc.auth import load_credentials
except ModuleNotFoundError:
    _add_cambc_site_packages()
    from cambc.api import api_get
    from cambc.auth import load_credentials

from tools.replay_schema import replay_message_class


ANALYSIS_DIR = ROOT / ".dist" / "replay_analysis"

TEAM_NAMES = {0: "TEAM_A", 1: "TEAM_B"}
ENV_NAMES = {
    0: "empty",
    1: "wall",
    2: "ore_titanium",
    3: "ore_axionite",
}
RESOURCE_MOVE_AMOUNT = 10
EXEC_TIME_LIMIT_US = 2000


def decode_replay_file(path: Path):
    replay = replay_message_class()()
    replay.ParseFromString(path.read_bytes())
    return replay


def entity_kind_name(entity) -> str:
    # These message-presence checks mirror the bundled visualiser schema.
    for field_name in (
        "builderBot",
        "conveyor",
        "splitter",
        "armouredConveyor",
        "bridge",
        "harvester",
        "foundry",
        "road",
        "barrier",
        "marker",
        "core",
        "gunner",
        "sentinel",
        "breach",
        "launcher",
    ):
        if entity.HasField(field_name):
            return field_name
    return "unknown"


def team_name(team_value: int) -> str:
    return TEAM_NAMES.get(int(team_value), f"TEAM_{team_value}")


def relativize(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(ROOT))
    except ValueError:
        return str(resolved)


def _new_team_summary() -> dict[str, Any]:
    return {
        "placements_by_kind": Counter(),
        "removals_by_kind": Counter(),
        "builder_moves": 0,
        "resource_transfers": 0,
        "builder_attacks": 0,
        "turret_fires": 0,
        "indicator_lines": 0,
        "indicator_dots": 0,
        "bot_turns": 0,
        "stdout_messages": 0,
        "stdout_samples": [],
        "exec_time_total_us": 0,
        "exec_time_max_us": 0,
        "turns_over_2ms": 0,
        "turns_over_2ms_rate": 0.0,
        "tled_turns": 0,
        "builder_turns": 0,
        "builder_turns_over_2ms": 0,
        "builder_turns_over_2ms_rate": 0.0,
        "builder_no_progress_turns": 0,
        "builder_max_no_progress_streak": 0,
        "builder_stall_events": [],
        "builder_small_loop_events": [],
        "builder_max_small_loop_streak": 0,
        "small_loop_builders": [],
        "final_resources": {},
        "delivered_resources": {
            "titanium": 0,
            "raw_axionite": 0,
            "refined_axionite": 0,
        },
        "alive_by_kind": {},
    }


def _placement_adjacent_to(builder_position: tuple[int, int], placement_positions: set[tuple[int, int]]) -> bool:
    bx, by = builder_position
    for px, py in placement_positions:
        if abs(px - bx) + abs(py - by) <= 1:
            return True
    return False


def _core_tiles_for_team(replay) -> dict[str, set[tuple[int, int]]]:
    core_tiles = {TEAM_NAMES[0]: set(), TEAM_NAMES[1]: set()}
    for core in replay.map.cores:
        team = team_name(int(core.team))
        center_x = int(core.position.x)
        center_y = int(core.position.y)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                core_tiles[team].add((center_x + dx, center_y + dy))
    return core_tiles


def _map_environments(replay) -> dict[tuple[int, int], str]:
    environments: dict[tuple[int, int], str] = {}
    for y, row in enumerate(replay.map.rows):
        for x, tile in enumerate(row.tiles):
            environments[(x, y)] = ENV_NAMES.get(int(tile), str(int(tile)))
    return environments


def _infer_resource_name(
    resource_id: int,
    source_position: tuple[int, int],
    entities: dict[int, dict[str, Any]],
    environments: dict[tuple[int, int], str],
    known_types: dict[int, str],
) -> str | None:
    if resource_id in known_types:
        return known_types[resource_id]
    for entity in entities.values():
        if entity["position"] != source_position:
            continue
        if entity["kind"] == "foundry":
            known_types[resource_id] = "refined_axionite"
            return known_types[resource_id]
        if entity["kind"] == "harvester":
            environment = environments.get(source_position)
            if environment == "ore_titanium":
                known_types[resource_id] = "titanium"
                return known_types[resource_id]
            if environment == "ore_axionite":
                known_types[resource_id] = "raw_axionite"
                return known_types[resource_id]
    return None


def analyze_replay(
    replay,
    *,
    replay_path: str | None = None,
    match_id: str | None = None,
    game_number: int | None = None,
    map_name: str | None = None,
    map_seed: int | None = None,
    expected_winner_team_id: str | None = None,
    team_ids: dict[str, str] | None = None,
) -> dict[str, Any]:
    environment_counts = Counter()
    for row in replay.map.rows:
        for tile in row.tiles:
            environment_counts[ENV_NAMES.get(int(tile), str(int(tile)))] += 1

    entities: dict[int, dict[str, Any]] = {}
    no_progress_streaks: defaultdict[int, int] = defaultdict(int)
    team_summaries = {TEAM_NAMES[0]: _new_team_summary(), TEAM_NAMES[1]: _new_team_summary()}
    update_counts = Counter()
    repeated_position_counts: defaultdict[int, Counter] = defaultdict(Counter)
    builder_position_windows: defaultdict[int, deque[tuple[int, int]]] = defaultdict(lambda: deque(maxlen=24))
    builder_small_loop_streaks: defaultdict[int, int] = defaultdict(int)
    builder_small_loop_active: defaultdict[int, bool] = defaultdict(bool)
    small_loop_builders_by_team: dict[str, set[int]] = {TEAM_NAMES[0]: set(), TEAM_NAMES[1]: set()}
    core_tiles_by_team = _core_tiles_for_team(replay)
    environments_by_position = _map_environments(replay)
    resource_types: dict[int, str] = {}

    for turn_index, turn in enumerate(replay.turns):
        moved_builders: set[int] = set()
        attacked_builders: set[int] = set()
        placement_positions_by_team = {TEAM_NAMES[0]: set(), TEAM_NAMES[1]: set()}
        bot_outputs: dict[int, Any] = {}

        for update in turn.updates:
            if update.HasField("placeEntity"):
                update_counts["placeEntity"] += 1
                entity = update.placeEntity.entity
                kind = entity_kind_name(entity)
                position = (entity.position.x, entity.position.y)
                entity_state = {
                    "id": int(entity.id),
                    "team": team_name(int(entity.team)),
                    "kind": kind,
                    "position": position,
                    "hp": int(entity.hp),
                    "max_hp": int(entity.maxHp),
                }
                entities[int(entity.id)] = entity_state
                placement_positions_by_team[entity_state["team"]].add(position)
                team_summaries[entity_state["team"]]["placements_by_kind"][kind] += 1
            elif update.HasField("moveBuilderBot"):
                update_counts["moveBuilderBot"] += 1
                builder_id = int(update.moveBuilderBot.id)
                moved_builders.add(builder_id)
                if builder_id in entities:
                    entities[builder_id]["position"] = (update.moveBuilderBot.to.x, update.moveBuilderBot.to.y)
                    team_summaries[entities[builder_id]["team"]]["builder_moves"] += 1
            elif update.HasField("removeEntity"):
                update_counts["removeEntity"] += 1
                entity_id = int(update.removeEntity.id)
                removed = entities.pop(entity_id, None)
                if removed is not None:
                    team_summaries[removed["team"]]["removals_by_kind"][removed["kind"]] += 1
            elif update.HasField("distributeResources"):
                update_counts["distributeResources"] += 1
                for resource_move in update.distributeResources.moves:
                    source = getattr(resource_move, "from")
                    destination = resource_move.to
                    source_position = (source.x, source.y)
                    resource_name = _infer_resource_name(
                        int(resource_move.resourceId),
                        source_position,
                        entities,
                        environments_by_position,
                        resource_types,
                    )
                    for entity in entities.values():
                        if entity["position"] == source_position:
                            team_summaries[entity["team"]]["resource_transfers"] += 1
                            break
                    if resource_name is None:
                        continue
                    destination_position = (destination.x, destination.y)
                    for team, core_tiles in core_tiles_by_team.items():
                        if destination_position in core_tiles:
                            team_summaries[team]["delivered_resources"][resource_name] += RESOURCE_MOVE_AMOUNT
                            break
            elif update.HasField("updateHp"):
                update_counts["updateHp"] += 1
                entity_id = int(update.updateHp.id)
                if entity_id in entities:
                    entities[entity_id]["hp"] += int(update.updateHp.delta)
            elif update.HasField("updatePlayers"):
                update_counts["updatePlayers"] += 1
                players = update.updatePlayers.players
                team_summaries[TEAM_NAMES[0]]["final_resources"] = {
                    "titanium": int(players.a.titanium),
                    "axionite": int(players.a.axionite),
                    "resources_collected": int(players.a.resourcesCollected),
                    "titanium_collected": int(players.a.titaniumCollected),
                    "axionite_collected": int(players.a.axioniteCollected),
                }
                team_summaries[TEAM_NAMES[1]]["final_resources"] = {
                    "titanium": int(players.b.titanium),
                    "axionite": int(players.b.axionite),
                    "resources_collected": int(players.b.resourcesCollected),
                    "titanium_collected": int(players.b.titaniumCollected),
                    "axionite_collected": int(players.b.axioniteCollected),
                }
            elif update.HasField("setActionCooldown"):
                update_counts["setActionCooldown"] += 1
            elif update.HasField("setMoveCooldown"):
                update_counts["setMoveCooldown"] += 1
            elif update.HasField("botOutput"):
                update_counts["botOutput"] += 1
                bot_outputs[int(update.botOutput.id)] = update.botOutput
            elif update.HasField("indicatorLine"):
                update_counts["indicatorLine"] += 1
                indicator = update.indicatorLine
                entity = entities.get(int(indicator.id))
                if entity is not None:
                    team_summaries[entity["team"]]["indicator_lines"] += 1
            elif update.HasField("indicatorDot"):
                update_counts["indicatorDot"] += 1
                indicator = update.indicatorDot
                entity = entities.get(int(indicator.id))
                if entity is not None:
                    team_summaries[entity["team"]]["indicator_dots"] += 1
            elif update.HasField("builderAttack"):
                update_counts["builderAttack"] += 1
                builder_id = int(update.builderAttack.id)
                attacked_builders.add(builder_id)
                entity = entities.get(builder_id)
                if entity is not None:
                    team_summaries[entity["team"]]["builder_attacks"] += 1
            elif update.HasField("fireTurret"):
                update_counts["fireTurret"] += 1
                source = getattr(update.fireTurret, "from")
                from_position = (source.x, source.y)
                for entity in entities.values():
                    if entity["position"] == from_position:
                        team_summaries[entity["team"]]["turret_fires"] += 1
                        break

        for bot_id, output in bot_outputs.items():
            entity = entities.get(bot_id)
            if entity is None:
                continue
            team_summary = team_summaries[entity["team"]]
            team_summary["bot_turns"] += 1
            exec_time = int(output.execTimeUs)
            team_summary["exec_time_total_us"] += exec_time
            team_summary["exec_time_max_us"] = max(team_summary["exec_time_max_us"], exec_time)
            if exec_time > EXEC_TIME_LIMIT_US:
                team_summary["turns_over_2ms"] += 1
            if bool(output.tled):
                team_summary["tled_turns"] += 1
            if output.stdout:
                team_summary["stdout_messages"] += 1
                if len(team_summary["stdout_samples"]) < 5:
                    team_summary["stdout_samples"].append(output.stdout)

            if entity["kind"] != "builderBot":
                continue

            team_summary["builder_turns"] += 1
            if exec_time > EXEC_TIME_LIMIT_US:
                team_summary["builder_turns_over_2ms"] += 1
            current_position = entity["position"]
            repeated_position_counts[bot_id][current_position] += 1
            window = builder_position_windows[bot_id]
            window.append(current_position)
            in_small_loop = len(window) == 24 and len(set(window)) <= 3
            if in_small_loop:
                builder_small_loop_streaks[bot_id] += 1
                team_summary["builder_max_small_loop_streak"] = max(
                    team_summary["builder_max_small_loop_streak"],
                    builder_small_loop_streaks[bot_id],
                )
                small_loop_builders_by_team[entity["team"]].add(bot_id)
                if not builder_small_loop_active[bot_id]:
                    team_summary["builder_small_loop_events"].append(
                        {
                            "bot_id": bot_id,
                            "turn": turn_index,
                            "window": 24,
                            "unique_positions": [
                                {"x": pos[0], "y": pos[1]}
                                for pos in sorted(set(window), key=lambda item: (item[0], item[1]))
                            ],
                        }
                    )
                builder_small_loop_active[bot_id] = True
            else:
                builder_small_loop_streaks[bot_id] = 0
                builder_small_loop_active[bot_id] = False
            productive = (
                bot_id in moved_builders
                or bot_id in attacked_builders
                or _placement_adjacent_to(current_position, placement_positions_by_team[entity["team"]])
            )
            if productive:
                no_progress_streaks[bot_id] = 0
                continue

            no_progress_streaks[bot_id] += 1
            team_summary["builder_no_progress_turns"] += 1
            team_summary["builder_max_no_progress_streak"] = max(
                team_summary["builder_max_no_progress_streak"],
                no_progress_streaks[bot_id],
            )
            if no_progress_streaks[bot_id] in (8, 16, 32):
                team_summary["builder_stall_events"].append(
                    {
                        "bot_id": bot_id,
                        "turn": turn_index,
                        "streak": no_progress_streaks[bot_id],
                        "position": {"x": current_position[0], "y": current_position[1]},
                    }
                )

    for summary in team_summaries.values():
        bot_turns = int(summary["bot_turns"])
        if bot_turns > 0:
            summary["turns_over_2ms_rate"] = float(summary["turns_over_2ms"]) / float(bot_turns)
        else:
            summary["turns_over_2ms_rate"] = 0.0
        builder_turns = int(summary["builder_turns"])
        if builder_turns > 0:
            summary["builder_turns_over_2ms_rate"] = float(summary["builder_turns_over_2ms"]) / float(
                builder_turns
            )
        else:
            summary["builder_turns_over_2ms_rate"] = 0.0
    for team, builders in small_loop_builders_by_team.items():
        team_summaries[team]["small_loop_builders"] = sorted(builders)

    replay_winner = None
    if replay.HasField("winner"):
        replay_winner = team_name(int(replay.winner))
    elif expected_winner_team_id is not None and team_ids is not None:
        for candidate_name, candidate_team_id in team_ids.items():
            if candidate_team_id == expected_winner_team_id:
                replay_winner = candidate_name
                break

    hot_builders = []
    for bot_id, position_counts in repeated_position_counts.items():
        most_common_position, repeat_count = position_counts.most_common(1)[0]
        hot_builders.append(
            {
                "bot_id": bot_id,
                "most_repeated_position": {"x": most_common_position[0], "y": most_common_position[1]},
                "repeat_count": repeat_count,
                "max_no_progress_streak": no_progress_streaks[bot_id],
            }
        )
    hot_builders.sort(key=lambda item: (item["repeat_count"], item["max_no_progress_streak"]), reverse=True)

    alive_by_team: dict[str, Counter] = {TEAM_NAMES[0]: Counter(), TEAM_NAMES[1]: Counter()}
    for entity in entities.values():
        alive_by_team[entity["team"]][entity["kind"]] += 1
    for team, counts in alive_by_team.items():
        team_summaries[team]["alive_by_kind"] = dict(sorted(counts.items()))

    return {
        "metadata": {
            "match_id": match_id,
            "game_number": game_number,
            "replay_path": replay_path,
            "map_name": map_name,
            "map_seed": map_seed,
            "winner": replay_winner,
            "turns": len(replay.turns),
        },
        "map": {
            "width": int(replay.map.width),
            "height": int(replay.map.height),
            "environment_counts": dict(sorted(environment_counts.items())),
            "cores": [
                {
                    "id": int(core.id),
                    "team": team_name(int(core.team)),
                    "position": {"x": int(core.position.x), "y": int(core.position.y)},
                }
                for core in replay.map.cores
            ],
        },
        "updates": dict(sorted(update_counts.items())),
        "teams": {
            team: {
                **summary,
                "placements_by_kind": dict(sorted(summary["placements_by_kind"].items())),
                "removals_by_kind": dict(sorted(summary["removals_by_kind"].items())),
            }
            for team, summary in team_summaries.items()
        },
        "repeat_position_hotspots": hot_builders[:10],
    }


def analyze_replay_path(path: Path, **metadata: Any) -> dict[str, Any]:
    replay = decode_replay_file(path)
    return analyze_replay(replay, replay_path=relativize(path), **metadata)


def _download_replay(url: str, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=30) as response:
        destination.write_bytes(response.read())
    return destination


def _match_is_complete(status: str | None) -> bool:
    return status in {"complete", "completed"}


def analyze_latest_team_matches(*, limit: int = 8, match_type: str = "ladder") -> dict[str, Any]:
    creds = load_credentials()
    team = creds.get("team") if creds else None
    if team is None or not team.get("id"):
        raise SystemExit("Not logged in with a team. Run `cambc login` first.")

    params = {"teamIds": team["id"], "limit": str(limit)}
    if match_type:
        params["type"] = match_type
    listing = api_get("/api/matches", params)
    completed = [match for match in listing.get("matches", []) if _match_is_complete(match.get("status"))]

    summaries = []
    for match in completed:
        payload = analyze_match(match["id"])
        payload["match"]["status"] = match.get("status")
        payload["match"]["created_at"] = match.get("createdAt")
        summaries.append(payload)

    return {
        "team": {"id": team["id"], "name": team.get("name")},
        "match_type": match_type,
        "requested_limit": limit,
        "fetched_count": len(summaries),
        "matches": summaries,
    }


def analyze_match(match_id: str, *, game_number: int | None = None) -> dict[str, Any]:
    match_data = api_get(f"/api/matches/{match_id}")
    match = match_data["match"]
    games = match_data.get("games", [])
    if game_number is not None:
        games = [game for game in games if game.get("gameNumber") == game_number]

    team_ids = {
        TEAM_NAMES[0]: match["teamAId"],
        TEAM_NAMES[1]: match["teamBId"],
    }
    summaries = []
    for game in games:
        replay_info = api_get(
            "/api/matches/replay",
            {"matchId": match_id, "game": str(game["gameNumber"])},
        )
        destination = ANALYSIS_DIR / "replays" / f"{match_id}_game_{game['gameNumber']}.replay26"
        downloaded = _download_replay(replay_info["url"], destination)
        summaries.append(
            analyze_replay_path(
                downloaded,
                match_id=match_id,
                game_number=int(game["gameNumber"]),
                map_name=game.get("mapName"),
                map_seed=game.get("mapSeed"),
                expected_winner_team_id=game.get("winnerId"),
                team_ids=team_ids,
            )
        )

    return {
        "match": {
            "id": match_id,
            "team_a": match.get("teamAName"),
            "team_a_id": match.get("teamAId"),
            "team_b": match.get("teamBName"),
            "team_b_id": match.get("teamBId"),
            "score_a": match.get("scoreA"),
            "score_b": match.get("scoreB"),
            "triggered_by": match.get("triggeredBy"),
            "team_a_version": match.get("teamAVersion"),
            "team_b_version": match.get("teamBVersion"),
        },
        "games": summaries,
    }


def default_output_path(
    match_id: str | None,
    replay_file: Path | None,
    *,
    latest_team_matches: bool = False,
    team_id: str | None = None,
) -> Path:
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    if latest_team_matches:
        team_suffix = team_id or "team"
        return ANALYSIS_DIR / f"latest_team_matches_{team_suffix}.json"
    if match_id is not None:
        return ANALYSIS_DIR / f"{match_id}.json"
    if replay_file is not None:
        return ANALYSIS_DIR / f"{replay_file.stem}.json"
    raise ValueError("Either match_id, replay_file, or latest_team_matches must be provided")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--match-id", default=None, help="Remote match ID to download and analyze.")
    parser.add_argument("--game", type=int, default=None, help="Optional game number within a match.")
    parser.add_argument("--replay-file", default=None, help="Local .replay26 file to analyze.")
    parser.add_argument(
        "--latest-team-matches",
        action="store_true",
        help="Download and analyze latest completed matches for the authenticated team.",
    )
    parser.add_argument("--limit", type=int, default=8, help="Match limit for --latest-team-matches.")
    parser.add_argument(
        "--match-type",
        choices=["ladder", "unrated"],
        default="ladder",
        help="Match type filter for --latest-team-matches.",
    )
    parser.add_argument("--output", default=None, help="Optional JSON output path.")
    args = parser.parse_args()

    selected_inputs = sum(bool(value) for value in (args.match_id, args.replay_file, args.latest_team_matches))
    if selected_inputs != 1:
        raise SystemExit("Choose exactly one of --match-id, --replay-file, or --latest-team-matches")

    payload: dict[str, Any]
    replay_path = Path(args.replay_file) if args.replay_file else None
    default_team_id: str | None = None
    if args.latest_team_matches:
        payload = analyze_latest_team_matches(limit=args.limit, match_type=args.match_type)
        default_team_id = payload["team"]["id"]
    elif args.match_id:
        payload = analyze_match(args.match_id, game_number=args.game)
    else:
        payload = {
            "games": [
                analyze_replay_path(replay_path),
            ]
        }

    output_path = (
        Path(args.output)
        if args.output
        else default_output_path(
            args.match_id,
            replay_path,
            latest_team_matches=args.latest_team_matches,
            team_id=default_team_id,
        )
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(output_path)


if __name__ == "__main__":
    main()
