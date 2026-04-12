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
EXEC_TIME_PRESSURE_THRESHOLDS_US = (
    (500, "0_5ms"),
    (1000, "1ms"),
    (1500, "1_5ms"),
    (EXEC_TIME_LIMIT_US, "2ms"),
)


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
    summary = {
        "placements_by_kind": Counter(),
        "removals_by_kind": Counter(),
        "builder_moves": 0,
        "resource_transfers": 0,
        "builder_attacks": 0,
        "turret_fires": 0,
        "indicator_lines": 0,
        "indicator_dots": 0,
        "bot_turns": 0,
        "bot_output_by_kind": Counter(),
        "bot_output_by_unit": Counter(),
        "stdout_messages": 0,
        "stdout_samples": [],
        "stdout_total_chars": 0,
        "stdout_average_length": 0.0,
        "stdout_max_length": 0,
        "stdout_unique_units": 0,
        "exec_time_total_us": 0,
        "exec_time_average_us": 0.0,
        "exec_time_max_us": 0,
        "tled_turns": 0,
        "exec_time_by_kind": {},
        "hot_units_by_exec_time": [],
        "builder_turns": 0,
        "builder_no_progress_turns": 0,
        "builder_max_no_progress_streak": 0,
        "builder_stall_events": [],
        "builder_small_loop_events": [],
        "builder_max_small_loop_streak": 0,
        "small_loop_builders": [],
        "builder_movement_summary": {},
        "indicator_summary": {},
        "hot_builders": [],
        "failure_signals": [],
        "final_resources": {},
        "delivered_resources": {
            "titanium": 0,
            "raw_axionite": 0,
            "refined_axionite": 0,
        },
        "core_delivery_ports": Counter(),
        "core_delivery_port_summary": {},
        "alive_by_kind": {},
    }
    _add_exec_pressure_fields(summary, "turns", include_rates=True)
    _add_exec_pressure_fields(summary, "builder_turns", include_rates=True)
    return summary


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


RECENT_PATH_LIMIT = 12
SMALL_LOOP_WINDOW = 24
STDOUT_SAMPLE_LIMIT = 8
INDICATOR_SAMPLE_LIMIT = 8
PER_UNIT_INDICATOR_SAMPLE_LIMIT = 2
HOT_UNIT_LIMIT = 5
HOT_BUILDER_LIMIT = 5


def _position_dict(position: tuple[int, int]) -> dict[str, int]:
    return {"x": int(position[0]), "y": int(position[1])}


def _append_capped(items: list[Any], item: Any, *, limit: int) -> None:
    if len(items) < limit:
        items.append(item)


def _exec_pressure_count_field(prefix: str, label: str) -> str:
    return f"{prefix}_over_{label}"


def _exec_pressure_rate_field(prefix: str, label: str) -> str:
    return f"{_exec_pressure_count_field(prefix, label)}_rate"


def _add_exec_pressure_fields(
    target: dict[str, Any],
    prefix: str,
    *,
    include_rates: bool = False,
) -> None:
    for _, label in EXEC_TIME_PRESSURE_THRESHOLDS_US:
        target[_exec_pressure_count_field(prefix, label)] = 0
        if include_rates:
            target[_exec_pressure_rate_field(prefix, label)] = 0.0


def _record_exec_pressure(target: dict[str, Any], prefix: str, exec_time_us: int) -> None:
    for threshold_us, label in EXEC_TIME_PRESSURE_THRESHOLDS_US:
        if exec_time_us > threshold_us:
            target[_exec_pressure_count_field(prefix, label)] += 1


def _finalize_exec_pressure_rates(target: dict[str, Any], prefix: str, denominator: int) -> None:
    for _, label in EXEC_TIME_PRESSURE_THRESHOLDS_US:
        count_field = _exec_pressure_count_field(prefix, label)
        rate_field = _exec_pressure_rate_field(prefix, label)
        target[rate_field] = (
            float(target[count_field]) / float(denominator)
            if denominator > 0
            else 0.0
        )


def _exec_pressure_output_fields(
    source: dict[str, Any],
    prefix: str,
    denominator: int,
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for _, label in EXEC_TIME_PRESSURE_THRESHOLDS_US:
        count_field = _exec_pressure_count_field(prefix, label)
        output[count_field] = int(source[count_field])
        output[_exec_pressure_rate_field(prefix, label)] = (
            float(source[count_field]) / float(denominator)
            if denominator > 0
            else 0.0
        )
    return output


def _new_exec_bucket() -> dict[str, int]:
    bucket = {"turns": 0, "total_us": 0, "max_us": 0, "tled_turns": 0}
    _add_exec_pressure_fields(bucket, "turns")
    return bucket


def _new_builder_tracker(bot_id: int, team: str, position: tuple[int, int], *, turn_index: int) -> dict[str, Any]:
    tracker = {
        "bot_id": bot_id,
        "team": team,
        "spawn_position": position,
        "first_seen_turn": turn_index,
        "active_turns": 0,
        "move_turns": 0,
        "revisit_turns": 0,
        "backtrack_turns": 0,
        "sum_displacement": 0,
        "max_displacement": 0,
        "stagnant_streak": 0,
        "max_stagnant_streak": 0,
        "travel_without_build_streak": 0,
        "travel_without_build_events": [],
        "indicator_turns": 0,
        "stdout_messages": 0,
        "stdout_total_chars": 0,
        "tled_turns": 0,
        "recent_path": deque(maxlen=RECENT_PATH_LIMIT),
        "visited_positions": set(),
        "position_counts": Counter(),
        "small_loop_window": deque(maxlen=SMALL_LOOP_WINDOW),
        "small_loop_streak": 0,
        "small_loop_active": False,
        "ping_pong_events": [],
        "path_switch_events": [],
        "stuck_talking_events": [],
        "stagnant_communicating_streak": 0,
        "indicator_target_switches_while_stagnant": 0,
        "last_indicator_target": None,
        "last_position": None,
        "prev_position": None,
        "line_samples": [],
        "dot_samples": [],
    }
    _add_exec_pressure_fields(tracker, "output_turns")
    return tracker


def _record_indicator_sample(tracker: dict[str, Any], *, lines: list[dict[str, Any]], dots: list[dict[str, Any]]) -> None:
    for line in lines:
        _append_capped(tracker["line_samples"], line, limit=PER_UNIT_INDICATOR_SAMPLE_LIMIT)
    for dot in dots:
        _append_capped(tracker["dot_samples"], dot, limit=PER_UNIT_INDICATOR_SAMPLE_LIMIT)


def _sorted_counter(counter: Counter[Any]) -> dict[str, int]:
    return {str(key): int(value) for key, value in sorted(counter.items(), key=lambda item: (-item[1], str(item[0])))}


def _finalize_core_delivery_ports(summary: dict[str, Any]) -> None:
    ports = summary.get("core_delivery_ports", Counter())
    total_amount = int(sum(ports.values()))
    top_ports = [
        {"position": _position_dict(position), "amount": int(amount)}
        for position, amount in ports.most_common(9)
    ]
    top1_amount = int(top_ports[0]["amount"]) if top_ports else 0
    top3_amount = int(sum(port["amount"] for port in top_ports[:3]))
    summary["core_delivery_ports"] = top_ports
    summary["core_delivery_port_summary"] = {
        "active_ports": len(ports),
        "total_amount": total_amount,
        "top1_share": (float(top1_amount) / float(total_amount)) if total_amount else 0.0,
        "top3_share": (float(top3_amount) / float(total_amount)) if total_amount else 0.0,
    }


def _movement_plan_hints(
    *,
    units_with_indicators: int,
    line_targets: Counter[tuple[int, int]],
    average_line_length: float,
) -> list[str]:
    if units_with_indicators == 0:
        return ["No replay-visible indicators were emitted, so movement intent is inferred only from motion."]
    hints: list[str] = []
    if line_targets:
        target, count = line_targets.most_common(1)[0]
        hints.append(
            f"Indicator lines repeatedly converged on {_position_dict(target)}, suggesting a shared movement target ({count} lines)."
        )
    if average_line_length >= 4.0:
        hints.append("Indicator lines are usually long-range, which suggests forward path planning rather than local nudges.")
    else:
        hints.append("Indicator lines are mostly short-range, which suggests local tile-to-tile repositioning.")
    return hints


def _finalize_exec_stats(
    *,
    summary: dict[str, Any],
    stdout_units: set[int],
    exec_by_unit: dict[int, dict[str, Any]],
    exec_by_kind: dict[str, dict[str, int]],
) -> None:
    bot_turns = int(summary["bot_turns"])
    summary["stdout_unique_units"] = len(stdout_units)
    if summary["stdout_messages"] > 0:
        summary["stdout_average_length"] = float(summary["stdout_total_chars"]) / float(summary["stdout_messages"])
    else:
        summary["stdout_average_length"] = 0.0
    if bot_turns > 0:
        summary["exec_time_average_us"] = float(summary["exec_time_total_us"]) / float(bot_turns)
    else:
        summary["exec_time_average_us"] = 0.0

    finalized_exec_by_kind: dict[str, Any] = {}
    for kind, bucket in sorted(exec_by_kind.items()):
        turns = int(bucket["turns"])
        finalized_exec_by_kind[kind] = {
            "turns": turns,
            "average_us": float(bucket["total_us"]) / float(turns) if turns else 0.0,
            "max_us": int(bucket["max_us"]),
            "tled_turns": int(bucket["tled_turns"]),
        }
        finalized_exec_by_kind[kind].update(
            _exec_pressure_output_fields(bucket, "turns", turns)
        )
    summary["exec_time_by_kind"] = finalized_exec_by_kind

    hot_units = sorted(
        exec_by_unit.values(),
        key=lambda item: (
            int(item["tled_turns"]),
            int(item["max_us"]),
            float(item["total_us"]) / float(item["turns"]) if item["turns"] else 0.0,
        ),
        reverse=True,
    )[:HOT_UNIT_LIMIT]
    summary["hot_units_by_exec_time"] = [
        {
            "bot_id": int(item["bot_id"]),
            "kind": item["kind"],
            "turns": int(item["turns"]),
            "average_us": float(item["total_us"]) / float(item["turns"]) if item["turns"] else 0.0,
            "max_us": int(item["max_us"]),
            "tled_turns": int(item["tled_turns"]),
            **_exec_pressure_output_fields(item, "turns", int(item["turns"])),
        }
        for item in hot_units
    ]


def _finalize_indicator_summary(
    *,
    line_samples: list[dict[str, Any]],
    dot_samples: list[dict[str, Any]],
    per_unit_indicator_samples: dict[int, dict[str, list[dict[str, Any]]]],
    line_targets: Counter[tuple[int, int]],
    line_lengths: list[int],
) -> dict[str, Any]:
    units_with_indicators = sum(
        1 for samples in per_unit_indicator_samples.values() if samples["lines"] or samples["dots"]
    )
    average_line_length = float(sum(line_lengths)) / float(len(line_lengths)) if line_lengths else 0.0
    return {
        "presence": "present" if units_with_indicators else "none",
        "units_with_indicators": units_with_indicators,
        "average_line_length": average_line_length,
        "common_targets": [
            {"target": _position_dict(position), "count": int(count)}
            for position, count in line_targets.most_common(5)
        ],
        "sample_lines": line_samples,
        "sample_dots": dot_samples,
        "per_unit_samples": {
            str(bot_id): {
                "lines": samples["lines"],
                "dots": samples["dots"],
            }
            for bot_id, samples in sorted(per_unit_indicator_samples.items())
            if samples["lines"] or samples["dots"]
        },
        "movement_plan_hints": _movement_plan_hints(
            units_with_indicators=units_with_indicators,
            line_targets=line_targets,
            average_line_length=average_line_length,
        ),
    }


def _finalize_builder_summary(
    *,
    summary: dict[str, Any],
    builders: dict[int, dict[str, Any]],
) -> None:
    if not builders:
        summary["builder_movement_summary"] = {
            "builders_seen": 0,
            "average_move_ratio": 0.0,
            "average_revisit_rate": 0.0,
            "average_displacement": 0.0,
            "average_backtrack_rate": 0.0,
            "path_traces": {},
        }
        summary["hot_builders"] = []
        return

    move_ratios: list[float] = []
    revisit_rates: list[float] = []
    displacement_averages: list[float] = []
    backtrack_rates: list[float] = []
    per_builder: dict[str, Any] = {}
    hot_builders: list[dict[str, Any]] = []

    for bot_id, tracker in sorted(builders.items()):
        active_turns = int(tracker["active_turns"])
        move_ratio = float(tracker["move_turns"]) / float(active_turns) if active_turns else 0.0
        revisit_rate = float(tracker["revisit_turns"]) / float(active_turns) if active_turns else 0.0
        average_displacement = float(tracker["sum_displacement"]) / float(active_turns) if active_turns else 0.0
        backtrack_rate = float(tracker["backtrack_turns"]) / float(active_turns) if active_turns else 0.0
        move_ratios.append(move_ratio)
        revisit_rates.append(revisit_rate)
        displacement_averages.append(average_displacement)
        backtrack_rates.append(backtrack_rate)

        per_builder[str(bot_id)] = {
            "spawn_position": _position_dict(tracker["spawn_position"]),
            "active_turns": active_turns,
            "move_ratio": move_ratio,
            "revisit_rate": revisit_rate,
            "average_displacement": average_displacement,
            "max_displacement": int(tracker["max_displacement"]),
            "backtrack_rate": backtrack_rate,
            "max_stagnant_streak": int(tracker["max_stagnant_streak"]),
            "travel_without_build_events": tracker["travel_without_build_events"],
            "recent_path": [_position_dict(position) for position in tracker["recent_path"]],
        }

        hot_builders.append(
            {
                "bot_id": bot_id,
                "spawn_position": _position_dict(tracker["spawn_position"]),
                "active_turns": active_turns,
                "move_ratio": move_ratio,
                "revisit_rate": revisit_rate,
                "backtrack_rate": backtrack_rate,
                "average_displacement": average_displacement,
                "max_stagnant_streak": int(tracker["max_stagnant_streak"]),
                "small_loop_streak": int(tracker["small_loop_streak"]),
                "travel_without_build_events": tracker["travel_without_build_events"][:2],
                "ping_pong_events": tracker["ping_pong_events"][:2],
                "path_switch_events": tracker["path_switch_events"][:2],
                "stuck_talking_events": tracker["stuck_talking_events"][:2],
                "stdout_messages": int(tracker["stdout_messages"]),
                "stdout_total_chars": int(tracker["stdout_total_chars"]),
                "indicator_turns": int(tracker["indicator_turns"]),
                "recent_path": [_position_dict(position) for position in tracker["recent_path"]],
                "indicator_samples": {
                    "lines": tracker["line_samples"],
                    "dots": tracker["dot_samples"],
                },
            }
        )

    hot_builders.sort(
        key=lambda item: (
            int(item["small_loop_streak"]),
            int(item["max_stagnant_streak"]),
            len(item["stuck_talking_events"]),
            len(item["path_switch_events"]),
            item["revisit_rate"],
        ),
        reverse=True,
    )
    summary["builder_movement_summary"] = {
        "builders_seen": len(builders),
        "average_move_ratio": float(sum(move_ratios)) / float(len(move_ratios)),
        "average_revisit_rate": float(sum(revisit_rates)) / float(len(revisit_rates)),
        "average_displacement": float(sum(displacement_averages)) / float(len(displacement_averages)),
        "average_backtrack_rate": float(sum(backtrack_rates)) / float(len(backtrack_rates)),
        "path_traces": per_builder,
    }
    summary["hot_builders"] = hot_builders[:HOT_BUILDER_LIMIT]


def _derive_failure_signals(summary: dict[str, Any]) -> list[str]:
    signals: list[str] = []
    builder_turns = int(summary["builder_turns"])
    bot_turns = int(summary["bot_turns"])
    resources_collected = int(summary["final_resources"].get("resources_collected", 0))
    delivered_total = int(summary["delivered_resources"]["titanium"]) + (
        4 * int(summary["delivered_resources"]["refined_axionite"])
    )
    hot_builders = summary.get("hot_builders", [])

    if int(summary["builder_max_small_loop_streak"]) >= 1 or summary["small_loop_builders"]:
        signals.append("small_loop")
    if int(summary["tled_turns"]) > 0 or float(summary["turns_over_2ms_rate"]) >= 0.05:
        signals.append("high_tle_pressure")
    if builder_turns > 0 and (
        float(summary["builder_no_progress_turns"]) / float(builder_turns) >= 0.30
        or int(summary["builder_max_no_progress_streak"]) >= 16
    ):
        signals.append("low_builder_progress")
    if any(builder["travel_without_build_events"] for builder in hot_builders):
        signals.append("travel_without_build")
    if any(builder["path_switch_events"] for builder in hot_builders):
        signals.append("path_switching")
    if any(builder["stuck_talking_events"] for builder in hot_builders):
        signals.append("idle_output_spam")
    if resources_collected >= 100 and delivered_total * 2 < resources_collected:
        signals.append("resource_delivery_gap")
    port_summary = summary.get("core_delivery_port_summary", {})
    if (
        int(port_summary.get("total_amount", 0)) >= 1000
        and (
            int(port_summary.get("active_ports", 0)) <= 3
            or float(port_summary.get("top3_share", 0.0)) >= 0.85
        )
    ):
        signals.append("core_port_concentration")
    if bot_turns > 0 and float(summary["stdout_messages"]) / float(bot_turns) >= 0.4 and summary["builder_moves"] <= 1:
        signals.append("output_without_progress")
    return signals


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
    small_loop_builders_by_team: dict[str, set[int]] = {TEAM_NAMES[0]: set(), TEAM_NAMES[1]: set()}
    core_tiles_by_team = _core_tiles_for_team(replay)
    environments_by_position = _map_environments(replay)
    resource_types: dict[int, str] = {}
    stdout_units_by_team: dict[str, set[int]] = {TEAM_NAMES[0]: set(), TEAM_NAMES[1]: set()}
    exec_by_unit_by_team: dict[str, dict[int, dict[str, Any]]] = {TEAM_NAMES[0]: {}, TEAM_NAMES[1]: {}}
    exec_by_kind_by_team: dict[str, dict[str, dict[str, int]]] = {
        TEAM_NAMES[0]: defaultdict(_new_exec_bucket),
        TEAM_NAMES[1]: defaultdict(_new_exec_bucket),
    }
    builder_trackers_by_team: dict[str, dict[int, dict[str, Any]]] = {TEAM_NAMES[0]: {}, TEAM_NAMES[1]: {}}
    line_samples_by_team: dict[str, list[dict[str, Any]]] = {TEAM_NAMES[0]: [], TEAM_NAMES[1]: []}
    dot_samples_by_team: dict[str, list[dict[str, Any]]] = {TEAM_NAMES[0]: [], TEAM_NAMES[1]: []}
    per_unit_indicator_samples_by_team: dict[str, dict[int, dict[str, list[dict[str, Any]]]]] = {
        TEAM_NAMES[0]: defaultdict(lambda: {"lines": [], "dots": []}),
        TEAM_NAMES[1]: defaultdict(lambda: {"lines": [], "dots": []}),
    }
    line_targets_by_team: dict[str, Counter[tuple[int, int]]] = {TEAM_NAMES[0]: Counter(), TEAM_NAMES[1]: Counter()}
    line_lengths_by_team: dict[str, list[int]] = {TEAM_NAMES[0]: [], TEAM_NAMES[1]: []}

    for turn_index, turn in enumerate(replay.turns):
        moved_builders: set[int] = set()
        attacked_builders: set[int] = set()
        placement_positions_by_team = {TEAM_NAMES[0]: set(), TEAM_NAMES[1]: set()}
        bot_outputs: dict[int, Any] = {}
        indicator_lines_by_bot: defaultdict[int, list[dict[str, Any]]] = defaultdict(list)
        indicator_dots_by_bot: defaultdict[int, list[dict[str, Any]]] = defaultdict(list)

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
                if kind == "builderBot":
                    builder_trackers_by_team[entity_state["team"]].setdefault(
                        int(entity.id),
                        _new_builder_tracker(int(entity.id), entity_state["team"], position, turn_index=turn_index),
                    )
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
                            team_summaries[team]["core_delivery_ports"][destination_position] += RESOURCE_MOVE_AMOUNT
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
                    sample = {
                        "turn": turn_index,
                        "bot_id": int(indicator.id),
                        "from": _position_dict((int(indicator.posA.x), int(indicator.posA.y))),
                        "to": _position_dict((int(indicator.posB.x), int(indicator.posB.y))),
                        "rgb": [int(indicator.r), int(indicator.g), int(indicator.b)],
                    }
                    indicator_lines_by_bot[int(indicator.id)].append(sample)
                    _append_capped(line_samples_by_team[entity["team"]], sample, limit=INDICATOR_SAMPLE_LIMIT)
                    _append_capped(
                        per_unit_indicator_samples_by_team[entity["team"]][int(indicator.id)]["lines"],
                        sample,
                        limit=PER_UNIT_INDICATOR_SAMPLE_LIMIT,
                    )
                    line_targets_by_team[entity["team"]][(int(indicator.posB.x), int(indicator.posB.y))] += 1
                    line_lengths_by_team[entity["team"]].append(
                        abs(int(indicator.posA.x) - int(indicator.posB.x))
                        + abs(int(indicator.posA.y) - int(indicator.posB.y))
                    )
            elif update.HasField("indicatorDot"):
                update_counts["indicatorDot"] += 1
                indicator = update.indicatorDot
                entity = entities.get(int(indicator.id))
                if entity is not None:
                    team_summaries[entity["team"]]["indicator_dots"] += 1
                    sample = {
                        "turn": turn_index,
                        "bot_id": int(indicator.id),
                        "position": _position_dict((int(indicator.pos.x), int(indicator.pos.y))),
                        "rgb": [int(indicator.r), int(indicator.g), int(indicator.b)],
                    }
                    indicator_dots_by_bot[int(indicator.id)].append(sample)
                    _append_capped(dot_samples_by_team[entity["team"]], sample, limit=INDICATOR_SAMPLE_LIMIT)
                    _append_capped(
                        per_unit_indicator_samples_by_team[entity["team"]][int(indicator.id)]["dots"],
                        sample,
                        limit=PER_UNIT_INDICATOR_SAMPLE_LIMIT,
                    )
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
            team_summary["bot_output_by_kind"][entity["kind"]] += 1
            team_summary["bot_output_by_unit"][bot_id] += 1
            _record_exec_pressure(team_summary, "turns", exec_time)
            if bool(output.tled):
                team_summary["tled_turns"] += 1

            exec_bucket = exec_by_kind_by_team[entity["team"]][entity["kind"]]
            exec_bucket["turns"] += 1
            exec_bucket["total_us"] += exec_time
            exec_bucket["max_us"] = max(exec_bucket["max_us"], exec_time)
            _record_exec_pressure(exec_bucket, "turns", exec_time)
            if bool(output.tled):
                exec_bucket["tled_turns"] += 1
            unit_exec = exec_by_unit_by_team[entity["team"]].setdefault(
                bot_id,
                {
                    "bot_id": bot_id,
                    "kind": entity["kind"],
                    "turns": 0,
                    "total_us": 0,
                    "max_us": 0,
                    "tled_turns": 0,
                },
            )
            if unit_exec["turns"] == 0:
                _add_exec_pressure_fields(unit_exec, "turns")
            unit_exec["turns"] += 1
            unit_exec["total_us"] += exec_time
            unit_exec["max_us"] = max(unit_exec["max_us"], exec_time)
            _record_exec_pressure(unit_exec, "turns", exec_time)
            if bool(output.tled):
                unit_exec["tled_turns"] += 1
            if output.stdout:
                team_summary["stdout_messages"] += 1
                stdout_text = str(output.stdout)
                stdout_units_by_team[entity["team"]].add(bot_id)
                team_summary["stdout_total_chars"] += len(stdout_text)
                team_summary["stdout_max_length"] = max(team_summary["stdout_max_length"], len(stdout_text))
                _append_capped(
                    team_summary["stdout_samples"],
                    {"turn": turn_index, "bot_id": bot_id, "kind": entity["kind"], "stdout": stdout_text},
                    limit=STDOUT_SAMPLE_LIMIT,
                )

            if entity["kind"] != "builderBot":
                continue

            team_summary["builder_turns"] += 1
            _record_exec_pressure(team_summary, "builder_turns", exec_time)
            tracker = builder_trackers_by_team[entity["team"]].setdefault(
                bot_id,
                _new_builder_tracker(bot_id, entity["team"], entity["position"], turn_index=turn_index),
            )
            current_position = entity["position"]
            tracker["active_turns"] += 1
            tracker["recent_path"].append(current_position)
            displacement = abs(current_position[0] - tracker["spawn_position"][0]) + abs(
                current_position[1] - tracker["spawn_position"][1]
            )
            tracker["sum_displacement"] += displacement
            tracker["max_displacement"] = max(tracker["max_displacement"], displacement)
            if current_position in tracker["visited_positions"]:
                tracker["revisit_turns"] += 1
            tracker["visited_positions"].add(current_position)
            tracker["position_counts"][current_position] += 1
            if output.stdout:
                tracker["stdout_messages"] += 1
                tracker["stdout_total_chars"] += len(str(output.stdout))
            _record_exec_pressure(tracker, "output_turns", exec_time)
            if bool(output.tled):
                tracker["tled_turns"] += 1
            if bot_id in moved_builders:
                tracker["move_turns"] += 1

            previous_position = tracker["last_position"]
            prev_position = tracker["prev_position"]
            if previous_position is not None and previous_position == current_position:
                tracker["stagnant_streak"] += 1
            else:
                tracker["stagnant_streak"] = 0
                tracker["indicator_target_switches_while_stagnant"] = 0
            tracker["max_stagnant_streak"] = max(tracker["max_stagnant_streak"], tracker["stagnant_streak"])
            if prev_position is not None and current_position == prev_position and previous_position != current_position:
                tracker["backtrack_turns"] += 1
                if len(tracker["ping_pong_events"]) < 2:
                    tracker["ping_pong_events"].append(
                        {"turn": turn_index, "position": _position_dict(current_position)}
                    )

            repeated_position_counts[bot_id][current_position] += 1
            window = tracker["small_loop_window"]
            window.append(current_position)
            in_small_loop = len(window) == SMALL_LOOP_WINDOW and len(set(window)) <= 3
            if in_small_loop:
                tracker["small_loop_streak"] += 1
                team_summary["builder_max_small_loop_streak"] = max(
                    team_summary["builder_max_small_loop_streak"],
                    tracker["small_loop_streak"],
                )
                small_loop_builders_by_team[entity["team"]].add(bot_id)
                if not tracker["small_loop_active"]:
                    team_summary["builder_small_loop_events"].append(
                        {
                            "bot_id": bot_id,
                            "turn": turn_index,
                            "window": SMALL_LOOP_WINDOW,
                            "unique_positions": [
                                {"x": pos[0], "y": pos[1]}
                                for pos in sorted(set(window), key=lambda item: (item[0], item[1]))
                            ],
                        }
                    )
                tracker["small_loop_active"] = True
            else:
                tracker["small_loop_streak"] = 0
                tracker["small_loop_active"] = False

            turn_lines = indicator_lines_by_bot.get(bot_id, [])
            turn_dots = indicator_dots_by_bot.get(bot_id, [])
            if turn_lines or turn_dots:
                tracker["indicator_turns"] += 1
                _record_indicator_sample(tracker, lines=turn_lines, dots=turn_dots)
            if turn_lines:
                current_target = (
                    int(turn_lines[-1]["to"]["x"]),
                    int(turn_lines[-1]["to"]["y"]),
                )
                if (
                    tracker["last_indicator_target"] is not None
                    and tracker["last_indicator_target"] != current_target
                    and tracker["stagnant_streak"] >= 2
                ):
                    tracker["indicator_target_switches_while_stagnant"] += 1
                    if tracker["indicator_target_switches_while_stagnant"] == 3 and len(tracker["path_switch_events"]) < 2:
                        tracker["path_switch_events"].append(
                            {
                                "turn": turn_index,
                                "from_target": _position_dict(tracker["last_indicator_target"]),
                                "to_target": _position_dict(current_target),
                            }
                        )
                tracker["last_indicator_target"] = current_target

            productive = (
                bot_id in moved_builders
                or bot_id in attacked_builders
                or _placement_adjacent_to(current_position, placement_positions_by_team[entity["team"]])
            )
            if bot_id in moved_builders and not _placement_adjacent_to(current_position, placement_positions_by_team[entity["team"]]):
                tracker["travel_without_build_streak"] += 1
                if tracker["travel_without_build_streak"] in (8, 16):
                    tracker["travel_without_build_events"].append(
                        {
                            "turn": turn_index,
                            "streak": tracker["travel_without_build_streak"],
                            "position": _position_dict(current_position),
                        }
                    )
            else:
                tracker["travel_without_build_streak"] = 0

            if tracker["stagnant_streak"] >= 4 and (output.stdout or turn_lines or turn_dots):
                tracker["stagnant_communicating_streak"] += 1
                if tracker["stagnant_communicating_streak"] == 4 and len(tracker["stuck_talking_events"]) < 2:
                    tracker["stuck_talking_events"].append(
                        {
                            "turn": turn_index,
                            "position": _position_dict(current_position),
                            "stagnant_streak": tracker["stagnant_streak"],
                        }
                    )
            else:
                tracker["stagnant_communicating_streak"] = 0

            if productive:
                no_progress_streaks[bot_id] = 0
            else:
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

            tracker["prev_position"] = tracker["last_position"]
            tracker["last_position"] = current_position

    for summary in team_summaries.values():
        bot_turns = int(summary["bot_turns"])
        _finalize_exec_pressure_rates(summary, "turns", bot_turns)
        builder_turns = int(summary["builder_turns"])
        _finalize_exec_pressure_rates(summary, "builder_turns", builder_turns)
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
        _finalize_exec_stats(
            summary=team_summaries[team],
            stdout_units=stdout_units_by_team[team],
            exec_by_unit=exec_by_unit_by_team[team],
            exec_by_kind=exec_by_kind_by_team[team],
        )
        _finalize_builder_summary(
            summary=team_summaries[team],
            builders=builder_trackers_by_team[team],
        )
        _finalize_core_delivery_ports(team_summaries[team])
        team_summaries[team]["indicator_summary"] = _finalize_indicator_summary(
            line_samples=line_samples_by_team[team],
            dot_samples=dot_samples_by_team[team],
            per_unit_indicator_samples=per_unit_indicator_samples_by_team[team],
            line_targets=line_targets_by_team[team],
            line_lengths=line_lengths_by_team[team],
        )
        team_summaries[team]["failure_signals"] = _derive_failure_signals(team_summaries[team])

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
                "bot_output_by_kind": dict(sorted(summary["bot_output_by_kind"].items())),
                "bot_output_by_unit": _sorted_counter(summary["bot_output_by_unit"]),
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
