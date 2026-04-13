from __future__ import annotations

from pathlib import Path

from tools.analyze_replay import analyze_replay, analyze_replay_path
from tools.replay_schema import replay_message_class


def _empty_map(replay) -> None:
    replay.map.width = 5
    replay.map.height = 5
    for y in range(5):
        row = replay.map.rows.add()
        row.tiles.extend([0, 2 if y == 0 else 0, 0, 0, 0])

    core_a = replay.map.cores.add()
    core_a.id = 100
    core_a.team = 0
    core_a.position.x = 0
    core_a.position.y = 0

    core_b = replay.map.cores.add()
    core_b.id = 200
    core_b.team = 1
    core_b.position.x = 4
    core_b.position.y = 4


def _place_builder(turn, *, bot_id: int, team: int, x: int, y: int) -> None:
    entity = turn.updates.add().placeEntity.entity
    entity.id = bot_id
    entity.team = team
    entity.position.x = x
    entity.position.y = y
    entity.hp = 10
    entity.maxHp = 10
    entity.builderBot.actionCooldown = 0
    entity.builderBot.moveCooldown = 0


def _place_harvester(turn, *, entity_id: int, team: int, x: int, y: int) -> None:
    entity = turn.updates.add().placeEntity.entity
    entity.id = entity_id
    entity.team = team
    entity.position.x = x
    entity.position.y = y
    entity.hp = 10
    entity.maxHp = 10
    entity.harvester.resourceType = 1


def _move_builder(turn, *, bot_id: int, x: int, y: int) -> None:
    update = turn.updates.add().moveBuilderBot
    update.id = bot_id
    update.to.x = x
    update.to.y = y


def _bot_output(turn, *, bot_id: int, exec_us: int, stdout: str = "", tled: bool = False) -> None:
    output = turn.updates.add().botOutput
    output.id = bot_id
    output.execTimeUs = exec_us
    output.stdout = stdout
    output.tled = tled


def _indicator_line(turn, *, bot_id: int, x1: int, y1: int, x2: int, y2: int) -> None:
    line = turn.updates.add().indicatorLine
    line.id = bot_id
    line.posA.x = x1
    line.posA.y = y1
    line.posB.x = x2
    line.posB.y = y2
    line.r = 0
    line.g = 255
    line.b = 0


def _indicator_dot(turn, *, bot_id: int, x: int, y: int) -> None:
    dot = turn.updates.add().indicatorDot
    dot.id = bot_id
    dot.pos.x = x
    dot.pos.y = y
    dot.r = 255
    dot.g = 0
    dot.b = 0


def _player_snapshot(turn, *, team_a_ti: int, team_b_ti: int, collected_a: int = 150) -> None:
    players = turn.updates.add().updatePlayers.players
    players.a.titanium = team_a_ti
    players.a.axionite = 0
    players.a.resourcesCollected = collected_a
    players.a.titaniumCollected = collected_a
    players.a.axioniteCollected = 0
    players.b.titanium = team_b_ti
    players.b.axionite = 0
    players.b.resourcesCollected = 20
    players.b.titaniumCollected = 20
    players.b.axioniteCollected = 0


def _resource_move(turn, *, from_x: int, from_y: int, to_x: int, to_y: int) -> None:
    move = turn.updates.add().distributeResources.moves.add()
    getattr(move, "from").x = from_x
    getattr(move, "from").y = from_y
    move.to.x = to_x
    move.to.y = to_y
    move.resourceId = 1


def _sample_replay():
    replay = replay_message_class()()
    _empty_map(replay)

    turn0 = replay.turns.add()
    _place_builder(turn0, bot_id=1, team=0, x=1, y=1)
    _place_builder(turn0, bot_id=2, team=1, x=3, y=3)
    _place_harvester(turn0, entity_id=10, team=0, x=1, y=0)
    _bot_output(turn0, bot_id=1, exec_us=1000, stdout="")
    _player_snapshot(turn0, team_a_ti=120, team_b_ti=120)

    turn1 = replay.turns.add()
    _move_builder(turn1, bot_id=1, x=2, y=1)
    _resource_move(turn1, from_x=1, from_y=0, to_x=0, to_y=0)
    _indicator_line(turn1, bot_id=1, x1=2, y1=1, x2=4, y2=1)
    _indicator_dot(turn1, bot_id=1, x=2, y=1)
    _bot_output(turn1, bot_id=1, exec_us=2500, stdout="rush", tled=True)
    _player_snapshot(turn1, team_a_ti=110, team_b_ti=120)

    turn2 = replay.turns.add()
    _move_builder(turn2, bot_id=1, x=1, y=1)
    _resource_move(turn2, from_x=1, from_y=0, to_x=0, to_y=0)
    _indicator_line(turn2, bot_id=1, x1=1, y1=1, x2=4, y2=1)
    _bot_output(turn2, bot_id=1, exec_us=1800, stdout="")
    _player_snapshot(turn2, team_a_ti=105, team_b_ti=120)

    turn3 = replay.turns.add()
    _indicator_line(turn3, bot_id=1, x1=1, y1=1, x2=4, y2=2)
    _bot_output(turn3, bot_id=1, exec_us=1300, stdout="hold-a")
    _player_snapshot(turn3, team_a_ti=100, team_b_ti=120)

    turn4 = replay.turns.add()
    _indicator_line(turn4, bot_id=1, x1=1, y1=1, x2=3, y2=2)
    _bot_output(turn4, bot_id=1, exec_us=1200, stdout="hold-b")
    _player_snapshot(turn4, team_a_ti=95, team_b_ti=120)

    turn5 = replay.turns.add()
    _indicator_line(turn5, bot_id=1, x1=1, y1=1, x2=4, y2=2)
    _bot_output(turn5, bot_id=1, exec_us=1250, stdout="hold-c")
    _player_snapshot(turn5, team_a_ti=90, team_b_ti=120)

    turn6 = replay.turns.add()
    _indicator_line(turn6, bot_id=1, x1=1, y1=1, x2=2, y2=4)
    _bot_output(turn6, bot_id=1, exec_us=1100, stdout="hold-d")
    _player_snapshot(turn6, team_a_ti=85, team_b_ti=120)

    replay.winner = 0
    return replay


def test_analyze_replay_adds_output_and_indicator_summaries():
    payload = analyze_replay(_sample_replay(), map_name="sample.map26")
    team_a = payload["teams"]["TEAM_A"]
    team_b = payload["teams"]["TEAM_B"]

    assert payload["metadata"]["winner"] == "TEAM_A"
    assert payload["repeat_position_hotspots"]

    assert team_a["bot_output_by_kind"]["builderBot"] == 7
    assert team_a["bot_output_by_unit"]["1"] == 7
    assert team_a["stdout_messages"] == 5
    assert team_a["stdout_unique_units"] == 1
    assert team_a["stdout_average_length"] > 0
    assert team_a["exec_time_by_kind"]["builderBot"]["tled_turns"] == 1
    assert team_a["turns_over_0_5ms"] == 7
    assert team_a["turns_over_1ms"] == 6
    assert team_a["turns_over_1_5ms"] == 2
    assert team_a["turns_over_2ms"] == 1
    assert team_a["builder_turns_over_0_5ms"] == 7
    assert team_a["builder_turns_over_1ms"] == 6
    assert team_a["builder_turns_over_1_5ms"] == 2
    assert team_a["builder_turns_over_2ms"] == 1
    assert team_a["builder_turns_over_0_5ms_rate"] == 1.0
    assert team_a["builder_turns_over_1ms_rate"] == 6 / 7
    assert team_a["exec_time_by_kind"]["builderBot"]["turns_over_0_5ms"] == 7
    assert team_a["exec_time_by_kind"]["builderBot"]["turns_over_0_5ms_rate"] == 1.0
    assert team_a["exec_time_by_kind"]["builderBot"]["turns_over_1_5ms"] == 2
    assert team_a["exec_time_by_kind"]["builderBot"]["turns_over_1_5ms_rate"] == 2 / 7
    assert team_a["hot_units_by_exec_time"][0]["bot_id"] == 1
    assert team_a["hot_units_by_exec_time"][0]["turns_over_0_5ms"] == 7
    assert team_a["hot_units_by_exec_time"][0]["turns_over_0_5ms_rate"] == 1.0
    assert team_a["hot_units_by_exec_time"][0]["turns_over_1ms"] == 6
    assert team_a["hot_units_by_exec_time"][0]["turns_over_1ms_rate"] == 6 / 7
    assert team_a["delivered_resources"]["titanium"] == 20
    assert team_a["core_delivery_port_summary"]["active_ports"] == 1
    assert team_a["core_delivery_port_summary"]["top1_share"] == 1.0
    assert team_a["core_delivery_ports"][0] == {
        "position": {"x": 0, "y": 0},
        "amount": 20,
    }

    assert team_a["indicator_summary"]["presence"] == "present"
    assert team_a["indicator_summary"]["units_with_indicators"] == 1
    assert team_a["indicator_summary"]["sample_lines"]
    assert team_a["indicator_summary"]["per_unit_samples"]["1"]["dots"]
    assert team_b["indicator_summary"]["presence"] == "none"


def test_analyze_replay_detects_builder_path_churn_and_failure_signals():
    payload = analyze_replay(_sample_replay(), map_name="sample.map26")
    team_a = payload["teams"]["TEAM_A"]
    hot_builder = team_a["hot_builders"][0]
    movement = team_a["builder_movement_summary"]

    assert "1" in movement["path_traces"]
    assert hot_builder["backtrack_rate"] > 0
    assert hot_builder["path_switch_events"]
    assert "high_tle_pressure" in team_a["failure_signals"]
    assert "low_builder_progress" in team_a["failure_signals"]
    assert "path_switching" in team_a["failure_signals"]


def test_analyze_replay_path_preserves_existing_top_level_shape(tmp_path: Path):
    replay_path = tmp_path / "sample.replay26"
    replay_path.write_bytes(_sample_replay().SerializeToString())

    payload = analyze_replay_path(replay_path, map_name="sample.map26")

    assert set(payload) == {"metadata", "map", "updates", "teams", "repeat_position_hotspots"}
    assert "placements_by_kind" in payload["teams"]["TEAM_A"]
    assert "removals_by_kind" in payload["teams"]["TEAM_A"]
