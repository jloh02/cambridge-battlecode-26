from __future__ import annotations

from tools.review_match_with_openai import (
    build_strategy_prompt,
    render_review_markdown,
    resolve_focus_replay_team,
)


def _match_payload() -> dict[str, object]:
    return {
        "match": {
            "id": "match-123",
            "team_a": "Blue Dragon",
            "team_b": "Red Fox",
            "score_a": 3,
            "score_b": 2,
        },
        "games": [],
    }


def test_resolve_focus_replay_team_uses_match_names():
    assert resolve_focus_replay_team(_match_payload(), "Blue Dragon") == "TEAM_A"
    assert resolve_focus_replay_team(_match_payload(), "Red Fox") == "TEAM_B"


def test_prompt_explicitly_asks_for_attack_builder_and_sentinel_logic():
    prompt = build_strategy_prompt(
        match_payload=_match_payload(),
        game_payload={"metadata": {"game_number": 1}},
        replay_payload={"turns": []},
        replay_payload_scope="full_compact_replay",
        focus_team_name="Blue Dragon",
        focus_side_label="Silver",
    )

    assert "specific builder bots to an attack role" in prompt
    assert "How do they decide where sentinels point?" in prompt
    assert "How do they decide how many sentinels to build" in prompt
    assert "Compact full protobuf-parsed replay JSON" in prompt
    assert '"focus_replay_team": "TEAM_A"' in prompt


def test_render_review_markdown_includes_copyable_sections():
    markdown = render_review_markdown(
        match_payload=_match_payload(),
        focus_team_name="Blue Dragon",
        focus_side_label="Silver",
        per_game_reviews=[
            {
                "game": {
                    "metadata": {
                        "game_number": 1,
                        "map_name": "arena.map26",
                        "map_seed": 7,
                        "winner": "TEAM_A",
                        "turns": 314,
                    }
                },
                "replay_payload_scope": "full_compact_replay",
                "analysis": {
                    "focus_replay_team": "TEAM_A",
                    "confidence": "medium",
                    "attack_strategy_summary": "Blue Dragon converts one forward harvester into a sentinel nest.",
                    "builder_attack_roles": {
                        "has_dedicated_attack_builders": True,
                        "estimated_builder_count": 2,
                        "observed_facts": ["Two builders stay near the assault site."],
                        "inferred_rules": ["One builder likely places the harvester and one extends the ring."],
                        "evidence": [
                            {
                                "turn": 42,
                                "observation": "Two friendly builders remain adjacent to the harvester.",
                                "why_it_supports_the_claim": "They keep participating in the same assault cluster.",
                            }
                        ],
                    },
                    "sentinel_pointing_logic": {
                        "observed_facts": ["Sentinels face toward occupied enemy logistics lanes."],
                        "inferred_rules": ["Facing is chosen to cover the nearest high-traffic tiles."],
                        "evidence": [
                            {
                                "turn": 55,
                                "observation": "A new sentinel is placed facing east along the conveyor lane.",
                                "why_it_supports_the_claim": "The attack arc covers the harvester and its feeder line.",
                            }
                        ],
                    },
                    "sentinel_count_logic": {
                        "observed_facts": ["Four sentinels are built in this game."],
                        "inferred_rules": ["The build continues until the harvester is ringed on useful sides."],
                        "evidence": [
                            {
                                "turn": 63,
                                "observation": "The fourth sentinel completes the perimeter and no fifth sentinel follows.",
                                "why_it_supports_the_claim": "The cluster stops growing after the local ring is finished.",
                            }
                        ],
                    },
                    "movement_and_build_sequence": {
                        "steps": ["Approach harvester tile", "Drop harvester", "Rotate builders around it", "Fill ring"],
                        "observed_facts": ["Builders circle through adjacent open tiles before placements."],
                        "inferred_rules": ["Movement appears to reserve open ring tiles before each build."],
                        "evidence": [
                            {
                                "turn": 48,
                                "observation": "A builder steps off the ring and another takes the vacated tile before building.",
                                "why_it_supports_the_claim": "The assault needs short local repositioning to complete the shell.",
                            }
                        ],
                    },
                    "heuristics": ["Prefer enemy harvesters with exposed feeder lanes."],
                    "copyable_strategy": ["Build a forward harvester first, then fill the best ring tiles with sentinels."],
                    "other_notable_details": ["The assault stalls once the ring is complete."],
                    "unknowns_and_ambiguities": ["The replay does not prove whether roles are hard-coded or emergent."],
                },
            }
        ],
    )

    assert "# GPT-5.4 Replay Strategy Review: Blue Dragon" in markdown
    assert "## Game 1" in markdown
    assert "### Copyable Strategy" in markdown
    assert "Turn 42" in markdown
