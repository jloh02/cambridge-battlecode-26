from __future__ import annotations

import json
from pathlib import Path

from tools import benchmark_matrix, report


def test_evaluate_promotion_gate_defaults_to_80_percent_and_150k_avg() -> None:
    summary = {
        "per_opponent": {
            "jon-6": {
                "win_rate": 0.81,
                "candidate_tieq_avg": 150000.0,
                "candidate_tieq_worst": 1,
            }
        }
    }

    gate = benchmark_matrix.evaluate_promotion_gate("got-any-grapes", summary)

    assert gate["win_rate_threshold"] == 0.8
    assert gate["tieq_avg_threshold"] == 150000
    assert gate["tieq_worst_threshold"] == 0
    assert gate["qualifies_for_promotion"] is True


def test_evaluate_promotion_gate_ignores_worst_tieq_when_disabled() -> None:
    summary = {
        "per_opponent": {
            "jon-6": {
                "win_rate": 0.81,
                "candidate_tieq_avg": 150000.0,
                "candidate_tieq_worst": 0,
            }
        }
    }

    gate = benchmark_matrix.evaluate_promotion_gate("got-any-grapes", summary)

    assert gate["qualifies_for_promotion"] is True
    assert gate["failing_opponents"] == []


def test_summarize_matrix_tracks_win_conditions() -> None:
    records = [
        {
            "opponent": "jon-6",
            "winner": "A",
            "candidate_team": "TEAM_A",
            "win_condition": "Core destroyed",
            "turns": 100,
            "candidate_tieq": 200000,
            "candidate_metrics": {
                "delivered_titanium": 10,
                "delivered_refined_axionite": 20,
                "mined_titanium": 30,
                "mined_axionite": 40,
                "harvesters_alive": 5,
                "stored_titanium": 1,
                "stored_axionite": 2,
                "tled_turns": 0,
                "builder_max_small_loop_streak": 0,
            },
        },
        {
            "opponent": "jon-6",
            "winner": "A",
            "candidate_team": "TEAM_A",
            "win_condition": "Resources (tiebreak)",
            "turns": 120,
            "candidate_tieq": 160000,
            "candidate_metrics": {
                "delivered_titanium": 20,
                "delivered_refined_axionite": 10,
                "mined_titanium": 15,
                "mined_axionite": 5,
                "harvesters_alive": 4,
                "stored_titanium": 1,
                "stored_axionite": 2,
                "tled_turns": 2,
                "builder_max_small_loop_streak": 1,
            },
        },
    ]

    summary = benchmark_matrix.summarize_matrix("got-any-grapes", records)
    stats = summary["per_opponent"]["jon-6"]

    assert stats["win_condition_counts"] == {
        "Core destroyed": 1,
        "Resources (tiebreak)": 1,
    }
    assert stats["candidate_tled_turns"] == 2


def test_markdown_report_surfaces_tle_and_win_conditions() -> None:
    payload = {
        "candidate": "got-any-grapes",
        "recommendation": "hold",
        "promotion_gate": {
            "qualifies_for_promotion": False,
            "win_rate_threshold": 0.8,
            "tieq_avg_threshold": 150000,
            "tieq_worst_threshold": 0,
            "failing_opponents": ["jon-6"],
        },
        "summary": {
            "per_opponent": {
                "jon-6": {
                    "games": 16,
                    "wins": 12,
                    "losses": 4,
                    "draws": 0,
                    "win_rate": 0.75,
                    "candidate_tieq_avg": 150001.0,
                    "candidate_tieq_worst": 0,
                    "candidate_tled_turns": 3,
                    "win_condition_counts": {"Core destroyed": 2, "Resources (tiebreak)": 10},
                    "average_turns": 100.0,
                    "candidate_avg_delivered_titanium": 1.0,
                    "candidate_avg_delivered_refined_axionite": 2.0,
                    "candidate_avg_mined_titanium": 3.0,
                    "candidate_avg_mined_axionite": 4.0,
                }
            }
        },
    }

    markdown = report.markdown_report(payload)

    assert "TLE Turns" in markdown
    assert "Core destroyed:2" in markdown
    assert "Resources (tiebreak):10" in markdown


def test_csv_report_serializes_win_condition_counts(tmp_path) -> None:
    payload = {
        "summary": {
            "per_opponent": {
                "jon-6": {
                    "games": 16,
                    "wins": 12,
                    "losses": 4,
                    "draws": 0,
                    "win_rate": 0.75,
                    "candidate_tieq_avg": 150001.0,
                    "candidate_tieq_worst": 0,
                    "candidate_tled_turns": 3,
                    "win_condition_counts": {"Core destroyed": 2},
                    "average_turns": 100.0,
                    "candidate_avg_delivered_titanium": 1.0,
                    "candidate_avg_delivered_refined_axionite": 2.0,
                    "candidate_avg_mined_titanium": 3.0,
                    "candidate_avg_mined_axionite": 4.0,
                }
            }
        }
    }
    destination = tmp_path / "matrix.csv"

    report.csv_report(payload, destination)

    csv_text = destination.read_text(encoding="utf-8")
    assert "candidate_tled_turns" in csv_text
    assert '""Core destroyed"": 2' in csv_text


def test_build_schedule_balances_seats_for_even_game_count(tmp_path) -> None:
    jobs = benchmark_matrix.build_schedule(
        "got-any-grapes",
        Path("/tmp/candidate"),
        "jon-6",
        Path("/tmp/opponent"),
        [Path("/tmp/maps/a.map26")],
        16,
        one_order=False,
        schedule_seed=1,
        output_dir=tmp_path,
    )

    seats = [job["display_label"].rsplit(":", 1)[-1] for job in jobs]
    assert seats.count("AB") == 8
    assert seats.count("BA") == 8
