"""Review Cambridge Battlecode replays with GPT-5.4 and emit Markdown.

The review flow is intentionally per-replay: each `.replay26` is downloaded,
protobuf-parsed, converted to JSON, and sent as its own OpenAI Responses API
request. This keeps one whole replay within a single model call while avoiding
multi-replay context overflow.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.analyze_replay import ANALYSIS_DIR, _download_replay, analyze_replay, decode_replay_file

try:
    from cambc.api import api_get
    from cambc.auth import load_credentials
except ModuleNotFoundError as exc:  # pragma: no cover - kept symmetric with analyze_replay.py.
    raise SystemExit("Missing cambc package in the active Python environment.") from exc


DEFAULT_MODEL = "gpt-5.4"
DEFAULT_OUTPUT_SUFFIX = "gpt54_strategy_review.md"
REPORTS_DIR = ROOT / "reports"
FULL_REPLAY_CHAR_BUDGET = 400_000
ENVIRONMENT_CODES = {"0": "empty", "1": "wall", "2": "ore_titanium", "3": "ore_axionite"}
TEAM_CODE_LEGEND = {0: "TEAM_A", 1: "TEAM_B"}
RESOURCE_CODE_LEGEND = {0: "none", 1: "titanium", 2: "raw_axionite", 3: "refined_axionite"}
DIRECTION_CODE_LEGEND = {
    0: "centre",
    1: "north",
    2: "northeast",
    3: "east",
    4: "southeast",
    5: "south",
    6: "southwest",
    7: "west",
    8: "northwest",
}
ENTITY_KIND_CODES = {
    "builderBot": "bb",
    "conveyor": "cv",
    "splitter": "sp",
    "armouredConveyor": "ac",
    "bridge": "br",
    "harvester": "hv",
    "foundry": "fd",
    "road": "rd",
    "barrier": "ba",
    "marker": "mk",
    "core": "co",
    "gunner": "gn",
    "sentinel": "se",
    "breach": "bc",
    "launcher": "la",
}
UPDATE_CODE_LEGEND = {
    "p": "placeEntity",
    "m": "moveBuilderBot",
    "r": "removeEntity",
    "d": "distributeResources",
    "h": "updateHp",
    "P": "updatePlayers",
    "a": "setActionCooldown",
    "v": "setMoveCooldown",
    "o": "botOutput",
    "l": "indicatorLine",
    "D": "indicatorDot",
    "f": "fireTurret",
    "b": "builderAttack",
}
def _entity_extra(entity: Any, kind_name: str) -> list[int] | None:
    if kind_name == "builderBot":
        payload = entity.builderBot
        return [int(payload.actionCooldown), int(payload.moveCooldown)]
    if kind_name in {"conveyor", "splitter", "armouredConveyor"}:
        payload = getattr(entity, kind_name)
        return [int(payload.direction), int(payload.stored)]
    if kind_name == "bridge":
        payload = entity.bridge
        return [int(payload.target.x), int(payload.target.y), int(payload.stored)]
    if kind_name == "harvester":
        payload = entity.harvester
        return [int(payload.cooldown), int(payload.resourceType)]
    if kind_name == "foundry":
        return [int(entity.foundry.stored)]
    if kind_name == "marker":
        return [int(entity.marker.value)]
    if kind_name == "core":
        return [int(entity.core.actionCooldown)]
    if kind_name in {"gunner", "sentinel", "breach"}:
        payload = getattr(entity, kind_name)
        return [int(payload.direction), int(payload.ammoType), int(payload.ammoAmount)]
    if kind_name == "launcher":
        payload = entity.launcher
        return [int(payload.ammoType), int(payload.ammoAmount)]
    return None


def _compact_entity(entity: Any) -> list[Any]:
    kind_name = None
    for candidate in ENTITY_KIND_CODES:
        if entity.HasField(candidate):
            kind_name = candidate
            break
    if kind_name is None:
        kind_name = "marker"
    data: list[Any] = [
        int(entity.id),
        int(entity.team),
        ENTITY_KIND_CODES[kind_name],
        int(entity.position.x),
        int(entity.position.y),
        int(entity.hp),
        int(entity.maxHp),
    ]
    extra = _entity_extra(entity, kind_name)
    if extra is not None:
        data.append(extra)
    return data


def _compact_update(update: Any) -> list[Any]:
    if update.HasField("placeEntity"):
        return ["p", _compact_entity(update.placeEntity.entity)]
    if update.HasField("moveBuilderBot"):
        return ["m", int(update.moveBuilderBot.id), int(update.moveBuilderBot.to.x), int(update.moveBuilderBot.to.y)]
    if update.HasField("removeEntity"):
        return ["r", int(update.removeEntity.id)]
    if update.HasField("distributeResources"):
        moves = []
        for move in update.distributeResources.moves:
            item = [
                int(getattr(move, "from").x),
                int(getattr(move, "from").y),
                int(move.to.x),
                int(move.to.y),
            ]
            if move.HasField("resourceId"):
                item.append(int(move.resourceId))
            moves.append(item)
        return ["d", moves]
    if update.HasField("updateHp"):
        return ["h", int(update.updateHp.id), int(update.updateHp.delta)]
    if update.HasField("updatePlayers"):
        players = update.updatePlayers.players
        return [
            "P",
            [
                int(players.a.titanium),
                int(players.a.axionite),
                int(players.a.resourcesCollected),
                int(players.a.titaniumCollected),
                int(players.a.axioniteCollected),
            ],
            [
                int(players.b.titanium),
                int(players.b.axionite),
                int(players.b.resourcesCollected),
                int(players.b.titaniumCollected),
                int(players.b.axioniteCollected),
            ],
        ]
    if update.HasField("setActionCooldown"):
        return ["a", int(update.setActionCooldown.id), int(update.setActionCooldown.value)]
    if update.HasField("setMoveCooldown"):
        return ["v", int(update.setMoveCooldown.id), int(update.setMoveCooldown.value)]
    if update.HasField("botOutput"):
        payload = ["o", int(update.botOutput.id), int(update.botOutput.execTimeUs), bool(update.botOutput.tled)]
        if update.botOutput.stdout:
            payload.append(update.botOutput.stdout)
        return payload
    if update.HasField("indicatorLine"):
        payload = update.indicatorLine
        return [
            "l",
            int(payload.id),
            int(payload.posA.x),
            int(payload.posA.y),
            int(payload.posB.x),
            int(payload.posB.y),
            int(payload.r),
            int(payload.g),
            int(payload.b),
        ]
    if update.HasField("indicatorDot"):
        payload = update.indicatorDot
        return ["D", int(payload.id), int(payload.pos.x), int(payload.pos.y), int(payload.r), int(payload.g), int(payload.b)]
    if update.HasField("fireTurret"):
        return [
            "f",
            int(getattr(update.fireTurret, "from").x),
            int(getattr(update.fireTurret, "from").y),
            int(update.fireTurret.to.x),
            int(update.fireTurret.to.y),
        ]
    if update.HasField("builderAttack"):
        return ["b", int(update.builderAttack.id)]
    raise ValueError("Unknown update variant encountered while compacting replay.")


def compact_replay_payload(replay: Any) -> dict[str, Any]:
    payload = {
        "legend": {
            "teams": TEAM_CODE_LEGEND,
            "resources": RESOURCE_CODE_LEGEND,
            "directions": DIRECTION_CODE_LEGEND,
            "environments": ENVIRONMENT_CODES,
            "entity_kinds": ENTITY_KIND_CODES,
            "update_codes": UPDATE_CODE_LEGEND,
            "entity_shape": "[id, team, kind, x, y, hp, maxHp, extra?]",
            "update_shape": "Each turn is a list of update arrays whose first element is the update code.",
        },
        "map": {
            "w": int(replay.map.width),
            "h": int(replay.map.height),
            "r": ["".join(str(int(tile)) for tile in row.tiles) for row in replay.map.rows],
            "c": [
                [int(core.id), int(core.team), int(core.position.x), int(core.position.y)] for core in replay.map.cores
            ],
        },
        "t": [[_compact_update(update) for update in turn.updates] for turn in replay.turns],
    }
    if replay.HasField("winner"):
        payload["w"] = int(replay.winner)
    return payload


def compact_focus_team_extract(replay: Any, focus_team: int) -> dict[str, Any]:
    entities: dict[int, dict[str, Any]] = {}
    position_index: dict[tuple[int, int], dict[str, Any]] = {}
    sparse_turns: list[list[Any]] = []

    for turn_index, turn in enumerate(replay.turns):
        kept_updates: list[list[Any]] = []
        for update in turn.updates:
            keep = False
            if update.HasField("placeEntity"):
                entity = update.placeEntity.entity
                state = {
                    "team": int(entity.team),
                    "position": (int(entity.position.x), int(entity.position.y)),
                }
                entities[int(entity.id)] = state
                position_index[state["position"]] = state
                keep = True
            elif update.HasField("moveBuilderBot"):
                entity = entities.get(int(update.moveBuilderBot.id))
                keep = bool(entity and entity["team"] == focus_team)
                if entity is not None:
                    position_index.pop(entity["position"], None)
                    entity["position"] = (int(update.moveBuilderBot.to.x), int(update.moveBuilderBot.to.y))
                    position_index[entity["position"]] = entity
            elif update.HasField("removeEntity"):
                keep = True
                removed = entities.pop(int(update.removeEntity.id), None)
                if removed is not None:
                    position_index.pop(removed["position"], None)
            elif update.HasField("updatePlayers"):
                keep = True
            elif update.HasField("builderAttack"):
                entity = entities.get(int(update.builderAttack.id))
                keep = bool(entity and entity["team"] == focus_team)
            elif update.HasField("fireTurret"):
                source = getattr(update.fireTurret, "from")
                entity = position_index.get((int(source.x), int(source.y)))
                keep = bool(entity and entity["team"] == focus_team)
            elif update.HasField("indicatorLine"):
                entity = entities.get(int(update.indicatorLine.id))
                keep = bool(entity and entity["team"] == focus_team)
            elif update.HasField("indicatorDot"):
                entity = entities.get(int(update.indicatorDot.id))
                keep = bool(entity and entity["team"] == focus_team)

            if keep:
                kept_updates.append(_compact_update(update))
        if kept_updates:
            sparse_turns.append([turn_index, kept_updates])

    payload = {
        "legend": {
            "selection": [
                "This is a focus-team extract derived from the full parsed replay because the full replay exceeded the model context window.",
                "Included: all placements, all removals, all player resource snapshots, focus-team builder moves, focus-team builder attacks, focus-team turret fires, and focus-team indicators.",
                "Excluded: non-focus movement/cooldowns/botOutput and most generic HP/resource-transfer noise.",
            ],
            "teams": TEAM_CODE_LEGEND,
            "resources": RESOURCE_CODE_LEGEND,
            "directions": DIRECTION_CODE_LEGEND,
            "environments": ENVIRONMENT_CODES,
            "entity_kinds": ENTITY_KIND_CODES,
            "update_codes": UPDATE_CODE_LEGEND,
            "turn_shape": "[turn_index, updates]",
            "entity_shape": "[id, team, kind, x, y, hp, maxHp, extra?]",
            "update_shape": "Each kept update is an array whose first element is the update code.",
        },
        "scope": "focus_team_extract",
        "focus_team": focus_team,
        "map": {
            "w": int(replay.map.width),
            "h": int(replay.map.height),
            "r": ["".join(str(int(tile)) for tile in row.tiles) for row in replay.map.rows],
            "c": [
                [int(core.id), int(core.team), int(core.position.x), int(core.position.y)] for core in replay.map.cores
            ],
        },
        "t": sparse_turns,
    }
    if replay.HasField("winner"):
        payload["w"] = int(replay.winner)
    return payload


def compact_game_summary(game_payload: dict[str, Any], focus_replay_team: str) -> dict[str, Any]:
    opposing_team = "TEAM_A" if focus_replay_team == "TEAM_B" else "TEAM_B"
    return {
        "metadata": game_payload["metadata"],
        "updates": game_payload.get("updates", {}),
        "focus_team_summary": game_payload.get("teams", {}).get(focus_replay_team, {}),
        "opponent_team_summary": game_payload.get("teams", {}).get(opposing_team, {}),
        "repeat_position_hotspots": game_payload.get("repeat_position_hotspots", []),
    }


def _payload_char_size(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def choose_replay_payload(replay: Any, focus_replay_team: str) -> tuple[dict[str, Any], str]:
    full_payload = compact_replay_payload(replay)
    if _payload_char_size(full_payload) <= FULL_REPLAY_CHAR_BUDGET:
        return full_payload, "full_compact_replay"
    focus_team = 0 if focus_replay_team == "TEAM_A" else 1
    return compact_focus_team_extract(replay, focus_team), "focus_team_extract"


def _strategy_review_schema() -> dict[str, Any]:
    evidence_item = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "turn": {"type": "integer"},
            "observation": {"type": "string"},
            "why_it_supports_the_claim": {"type": "string"},
        },
        "required": ["turn", "observation", "why_it_supports_the_claim"],
    }
    section_with_evidence = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "observed_facts": {
                "type": "array",
                "items": {"type": "string"},
            },
            "inferred_rules": {
                "type": "array",
                "items": {"type": "string"},
            },
            "evidence": {
                "type": "array",
                "items": evidence_item,
            },
        },
        "required": ["observed_facts", "inferred_rules", "evidence"],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "focus_team": {"type": "string"},
            "focus_replay_team": {"type": "string"},
            "confidence": {
                "type": "string",
                "enum": ["high", "medium", "low"],
            },
            "attack_strategy_summary": {"type": "string"},
            "builder_attack_roles": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "has_dedicated_attack_builders": {"type": "boolean"},
                    "estimated_builder_count": {"type": ["integer", "null"]},
                    "observed_facts": {"type": "array", "items": {"type": "string"}},
                    "inferred_rules": {"type": "array", "items": {"type": "string"}},
                    "evidence": {"type": "array", "items": evidence_item},
                },
                "required": [
                    "has_dedicated_attack_builders",
                    "estimated_builder_count",
                    "observed_facts",
                    "inferred_rules",
                    "evidence",
                ],
            },
            "sentinel_pointing_logic": section_with_evidence,
            "sentinel_count_logic": section_with_evidence,
            "movement_and_build_sequence": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "steps": {"type": "array", "items": {"type": "string"}},
                    "observed_facts": {"type": "array", "items": {"type": "string"}},
                    "inferred_rules": {"type": "array", "items": {"type": "string"}},
                    "evidence": {"type": "array", "items": evidence_item},
                },
                "required": ["steps", "observed_facts", "inferred_rules", "evidence"],
            },
            "heuristics": {"type": "array", "items": {"type": "string"}},
            "copyable_strategy": {
                "type": "array",
                "items": {"type": "string"},
            },
            "other_notable_details": {
                "type": "array",
                "items": {"type": "string"},
            },
            "unknowns_and_ambiguities": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": [
            "focus_team",
            "focus_replay_team",
            "confidence",
            "attack_strategy_summary",
            "builder_attack_roles",
            "sentinel_pointing_logic",
            "sentinel_count_logic",
            "movement_and_build_sequence",
            "heuristics",
            "copyable_strategy",
            "other_notable_details",
            "unknowns_and_ambiguities",
        ],
    }


def build_strategy_prompt(
    *,
    match_payload: dict[str, Any],
    game_payload: dict[str, Any],
    replay_payload: dict[str, Any],
    replay_payload_scope: str,
    focus_team_name: str,
    focus_side_label: str,
) -> str:
    match_info = match_payload["match"]
    replay_team = resolve_focus_replay_team(match_payload, focus_team_name)
    compact_summary = compact_game_summary(game_payload, replay_team)
    instructions = [
        "You are reviewing one Cambridge Battlecode 2026 replay.",
        "Your job is to reverse engineer the attack strategy of the focus team from replay evidence only.",
        "Treat the replay payload as the ground truth. Do not claim anything that is not supported by the replay.",
        "Separate direct observations from inferred decision rules.",
        "When you infer a heuristic, explain what repeated behavior suggests that heuristic.",
        "Anchor important claims with concrete turn numbers from the replay.",
        "The user specifically wants enough detail to reproduce the strategy in code.",
        "",
        f"Focus team: {focus_team_name}",
        f"Focus side label from the match UI: {focus_side_label}",
        f"Focus replay team enum: {replay_team}",
        f"Replay payload scope: {replay_payload_scope}",
        f"Match teams: TEAM_A={match_info['team_a']}, TEAM_B={match_info['team_b']}",
        "",
        "Answer these questions as explicitly as the replay allows:",
        "1. Does the focus team appear to assign specific builder bots to an attack role? If yes, how many?",
        "2. How do they decide where sentinels point?",
        "3. How do they decide how many sentinels to build around an attack harvester?",
        "4. How do their bots move and sequence builds to assemble the sentinel ring around the harvester?",
        "5. What heuristics or triggers appear to control target choice, build order, orientation, and commitment?",
        "6. What additional concrete details would help an engineer copy this strategy?",
        "",
        "Important constraints:",
        "- Focus on the attack pattern around enemy harvesters and the surrounding sentinels.",
        "- If a claim is uncertain, say so explicitly and keep it in inferred rules or unknowns.",
        "- Prefer concise, implementation-oriented wording over vague strategic language.",
        "- Do not discuss source code or speculate about private intent beyond what the replay supports.",
        "",
        "Replay-level metadata JSON:",
        json.dumps(
            {
                "match": match_info,
                "game": game_payload["metadata"],
                "focus_team_name": focus_team_name,
                "focus_side_label": focus_side_label,
                "focus_replay_team": replay_team,
            },
            sort_keys=True,
        ),
        "",
        "Compact analyzer summary JSON:",
        json.dumps(compact_summary, sort_keys=True, separators=(",", ":")),
        "",
        "Compact full protobuf-parsed replay JSON:",
        json.dumps(replay_payload, sort_keys=True, separators=(",", ":")),
    ]
    return "\n".join(instructions)


def resolve_focus_replay_team(match_payload: dict[str, Any], focus_team_name: str) -> str:
    match_info = match_payload["match"]
    if match_info["team_a"] == focus_team_name:
        return "TEAM_A"
    if match_info["team_b"] == focus_team_name:
        return "TEAM_B"
    raise ValueError(
        f"Focus team {focus_team_name!r} is not present in match "
        f"({match_info['team_a']!r} vs {match_info['team_b']!r})."
    )


def _render_evidence_list(items: list[dict[str, Any]]) -> str:
    if not items:
        return "- None"
    return "\n".join(
        f"- Turn {item['turn']}: {item['observation']} ({item['why_it_supports_the_claim']})" for item in items
    )


def _render_string_list(items: list[str]) -> str:
    if not items:
        return "- None"
    return "\n".join(f"- {item}" for item in items)


def render_review_markdown(
    *,
    match_payload: dict[str, Any],
    focus_team_name: str,
    focus_side_label: str,
    per_game_reviews: list[dict[str, Any]],
) -> str:
    match_info = match_payload["match"]
    lines = [
        f"# GPT-5.4 Replay Strategy Review: {focus_team_name}",
        "",
        f"- Match ID: `{match_info['id']}`",
        f"- Focus team: `{focus_team_name}`",
        f"- Focus side label: `{focus_side_label}`",
        f"- Teams: `{match_info['team_a']}` vs `{match_info['team_b']}`",
        f"- Score: `{match_info['score_a']}` - `{match_info['score_b']}`",
        "",
        "This report was generated by protobuf-parsing each `.replay26` and sending one whole replay per GPT-5.4 request.",
        "",
    ]
    for review in per_game_reviews:
        game = review["game"]
        analysis = review["analysis"]
        lines.extend(
            [
                f"## Game {game['metadata']['game_number']}",
                "",
                f"- Map: `{game['metadata']['map_name']}`",
                f"- Seed: `{game['metadata']['map_seed']}`",
                f"- Winner: `{game['metadata']['winner']}`",
                f"- Turns: `{game['metadata']['turns']}`",
                f"- Focus replay team: `{analysis['focus_replay_team']}`",
                f"- Replay payload scope: `{review.get('replay_payload_scope', 'unknown')}`",
                f"- Model confidence: `{analysis['confidence']}`",
                "",
                "### Attack Strategy Summary",
                "",
                analysis["attack_strategy_summary"],
                "",
                "### Builder Attack Roles",
                "",
                f"- Dedicated attack builders observed: `{analysis['builder_attack_roles']['has_dedicated_attack_builders']}`",
                f"- Estimated builder count: `{analysis['builder_attack_roles']['estimated_builder_count']}`",
                "",
                "Observed facts:",
                _render_string_list(analysis["builder_attack_roles"]["observed_facts"]),
                "",
                "Inferred rules:",
                _render_string_list(analysis["builder_attack_roles"]["inferred_rules"]),
                "",
                "Evidence:",
                _render_evidence_list(analysis["builder_attack_roles"]["evidence"]),
                "",
                "### Sentinel Pointing Logic",
                "",
                "Observed facts:",
                _render_string_list(analysis["sentinel_pointing_logic"]["observed_facts"]),
                "",
                "Inferred rules:",
                _render_string_list(analysis["sentinel_pointing_logic"]["inferred_rules"]),
                "",
                "Evidence:",
                _render_evidence_list(analysis["sentinel_pointing_logic"]["evidence"]),
                "",
                "### Sentinel Count Logic",
                "",
                "Observed facts:",
                _render_string_list(analysis["sentinel_count_logic"]["observed_facts"]),
                "",
                "Inferred rules:",
                _render_string_list(analysis["sentinel_count_logic"]["inferred_rules"]),
                "",
                "Evidence:",
                _render_evidence_list(analysis["sentinel_count_logic"]["evidence"]),
                "",
                "### Movement And Build Sequence",
                "",
                "Steps:",
                _render_string_list(analysis["movement_and_build_sequence"]["steps"]),
                "",
                "Observed facts:",
                _render_string_list(analysis["movement_and_build_sequence"]["observed_facts"]),
                "",
                "Inferred rules:",
                _render_string_list(analysis["movement_and_build_sequence"]["inferred_rules"]),
                "",
                "Evidence:",
                _render_evidence_list(analysis["movement_and_build_sequence"]["evidence"]),
                "",
                "### Heuristics",
                "",
                _render_string_list(analysis["heuristics"]),
                "",
                "### Copyable Strategy",
                "",
                _render_string_list(analysis["copyable_strategy"]),
                "",
                "### Other Notable Details",
                "",
                _render_string_list(analysis["other_notable_details"]),
                "",
                "### Unknowns And Ambiguities",
                "",
                _render_string_list(analysis["unknowns_and_ambiguities"]),
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def default_output_path(match_id: str) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    return REPORTS_DIR / f"{match_id}_{DEFAULT_OUTPUT_SUFFIX}"


def default_json_output_path(markdown_output_path: Path) -> Path:
    return markdown_output_path.with_suffix(".json")


def _build_openai_client() -> Any:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("OPENAI_API_KEY is not set.")
    try:
        from openai import OpenAI
    except ModuleNotFoundError as exc:
        raise SystemExit("Missing `openai` package. Install it with `uv pip install openai`.") from exc
    return OpenAI(api_key=api_key, timeout=600.0)


def review_single_replay_with_openai(
    *,
    client: Any,
    model: str,
    prompt: str,
) -> dict[str, Any]:
    response = client.responses.create(
        model=model,
        input=[
            {
                "role": "system",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "You analyze Battlecode replays. "
                            "Use replay evidence only. "
                            "Produce structured JSON matching the schema."
                        ),
                    }
                ],
            },
            {
                "role": "user",
                "content": [{"type": "input_text", "text": prompt}],
            },
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "battlecode_replay_strategy_review",
                "strict": True,
                "schema": _strategy_review_schema(),
            }
        },
    )
    return json.loads(response.output_text)


def fetch_match_payload(match_id: str, *, game_number: int | None = None) -> dict[str, Any]:
    match_data = api_get(f"/api/matches/{match_id}")
    match = match_data["match"]
    games = match_data.get("games", [])
    if game_number is not None:
        games = [game for game in games if int(game.get("gameNumber")) == game_number]

    reviews = []
    for game in games:
        replay_info = api_get("/api/matches/replay", {"matchId": match_id, "game": str(game["gameNumber"])})
        destination = ANALYSIS_DIR / "replays" / f"{match_id}_game_{game['gameNumber']}.replay26"
        replay_path = _download_replay(replay_info["url"], destination)
        replay = decode_replay_file(replay_path)
        reviews.append(
            {
                "game": analyze_replay(
                    replay,
                    replay_path=str(replay_path.resolve()),
                    match_id=match_id,
                    game_number=int(game["gameNumber"]),
                    map_name=game.get("mapName"),
                    map_seed=game.get("mapSeed"),
                ),
                "replay_path": str(replay_path.resolve()),
            }
        )

    return {
        "match": {
            "id": match_id,
            "team_a": match.get("teamAName"),
            "team_b": match.get("teamBName"),
            "score_a": match.get("scoreA"),
            "score_b": match.get("scoreB"),
            "team_a_id": match.get("teamAId"),
            "team_b_id": match.get("teamBId"),
            "triggered_by": match.get("triggeredBy"),
            "team_a_version": match.get("teamAVersion"),
            "team_b_version": match.get("teamBVersion"),
        },
        "games": reviews,
    }


def run_review(
    *,
    match_id: str,
    focus_team_name: str,
    focus_side_label: str,
    model: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    load_credentials()
    match_payload = fetch_match_payload(match_id)
    focus_replay_team = resolve_focus_replay_team(match_payload, focus_team_name)
    client = _build_openai_client()

    per_game_reviews: list[dict[str, Any]] = []
    for item in match_payload["games"]:
        replay = decode_replay_file(Path(item["replay_path"]))
        replay_payload, replay_payload_scope = choose_replay_payload(replay, focus_replay_team)
        payload_chars = _payload_char_size(replay_payload)
        prompt = build_strategy_prompt(
            match_payload=match_payload,
            game_payload=item["game"],
            replay_payload=replay_payload,
            replay_payload_scope=replay_payload_scope,
            focus_team_name=focus_team_name,
            focus_side_label=focus_side_label,
        )
        print(
            f"reviewing game {item['game']['metadata']['game_number']} "
            f"scope={replay_payload_scope} payload_chars={payload_chars} prompt_chars={len(prompt)}",
            flush=True,
        )
        try:
            analysis = review_single_replay_with_openai(client=client, model=model, prompt=prompt)
        except Exception as exc:
            if replay_payload_scope != "full_compact_replay" or "context window" not in str(exc).lower():
                raise
            replay_payload_scope = "focus_team_extract"
            replay_payload = compact_focus_team_extract(replay, 0 if focus_replay_team == "TEAM_A" else 1)
            payload_chars = _payload_char_size(replay_payload)
            prompt = build_strategy_prompt(
                match_payload=match_payload,
                game_payload=item["game"],
                replay_payload=replay_payload,
                replay_payload_scope=replay_payload_scope,
                focus_team_name=focus_team_name,
                focus_side_label=focus_side_label,
            )
            print(
                f"retrying game {item['game']['metadata']['game_number']} "
                f"scope={replay_payload_scope} payload_chars={payload_chars} prompt_chars={len(prompt)}",
                flush=True,
            )
            analysis = review_single_replay_with_openai(client=client, model=model, prompt=prompt)
        print(f"finished game {item['game']['metadata']['game_number']}", flush=True)
        per_game_reviews.append(
            {
                "game": item["game"],
                "analysis": analysis,
                "replay_payload_scope": replay_payload_scope,
            }
        )
    return match_payload, per_game_reviews


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--match-id", required=True, help="Match ID to download and review.")
    parser.add_argument(
        "--focus-team",
        default="Blue Dragon",
        help="Team name whose strategy should be reverse engineered.",
    )
    parser.add_argument(
        "--focus-side-label",
        default="Silver",
        help="Human-facing side label from the match UI.",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help="OpenAI model to use.")
    parser.add_argument("--output", default=None, help="Markdown output path.")
    parser.add_argument("--json-output", default=None, help="Optional raw JSON output path.")
    args = parser.parse_args()

    match_payload, per_game_reviews = run_review(
        match_id=args.match_id,
        focus_team_name=args.focus_team,
        focus_side_label=args.focus_side_label,
        model=args.model,
    )

    output_path = Path(args.output) if args.output else default_output_path(args.match_id)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    markdown = render_review_markdown(
        match_payload=match_payload,
        focus_team_name=args.focus_team,
        focus_side_label=args.focus_side_label,
        per_game_reviews=per_game_reviews,
    )
    output_path.write_text(markdown, encoding="utf-8")

    json_output_path = Path(args.json_output) if args.json_output else default_json_output_path(output_path)
    json_output_path.write_text(
        json.dumps(
            {
                "match": match_payload["match"],
                "focus_team_name": args.focus_team,
                "focus_side_label": args.focus_side_label,
                "model": args.model,
                "games": per_game_reviews,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    print(output_path)


if __name__ == "__main__":
    main()
