"""Render benchmark JSON as Markdown or CSV."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def load_results(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _builder_pressure_rate(stats: dict, label: str) -> float:
    return float(stats.get(f"candidate_builder_turns_over_{label}_rate", 0.0))


def _matrix_markdown(payload: dict) -> str:
    summary = payload["summary"]
    gate = payload.get("promotion_gate", {})
    lines = [
        "# Benchmark Matrix Report",
        "",
        f"Candidate: `{payload['candidate']}`",
        "",
        f"Recommendation: `{payload.get('recommendation', 'unknown')}`",
        "",
        "| Opponent | Games | Wins | Losses | Draws | Win Rate | Avg TiEq | Worst TiEq | TLE Turns | >0.5ms | >1ms | >1.5ms | >2ms | Win Conditions | Avg Turns | Avg Del Ti | Avg Del rAx | Avg Mined Ti | Avg Mined Ax |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for opponent, stats in summary.get("per_opponent", {}).items():
        win_conditions = ", ".join(
            f"{name}:{count}" for name, count in stats.get("win_condition_counts", {}).items()
        ) or "none"
        lines.append(
            "| {opponent} | {games} | {wins} | {losses} | {draws} | {win_rate:.1%} | {tieq_avg:.1f} | {tieq_worst} | {tled} | {over_0_5:.1%} | {over_1:.1%} | {over_1_5:.1%} | {over_2:.1%} | {win_conditions} | {avg_turns:.1f} | {del_ti:.1f} | {del_rax:.1f} | {mined_ti:.1f} | {mined_ax:.1f} |".format(
                opponent=opponent,
                games=stats["games"],
                wins=stats["wins"],
                losses=stats["losses"],
                draws=stats["draws"],
                win_rate=stats["win_rate"],
                tieq_avg=stats["candidate_tieq_avg"],
                tieq_worst=stats["candidate_tieq_worst"],
                tled=stats["candidate_tled_turns"],
                over_0_5=_builder_pressure_rate(stats, "0_5ms"),
                over_1=_builder_pressure_rate(stats, "1ms"),
                over_1_5=_builder_pressure_rate(stats, "1_5ms"),
                over_2=_builder_pressure_rate(stats, "2ms"),
                win_conditions=win_conditions,
                avg_turns=stats["average_turns"],
                del_ti=stats["candidate_avg_delivered_titanium"],
                del_rax=stats["candidate_avg_delivered_refined_axionite"],
                mined_ti=stats["candidate_avg_mined_titanium"],
                mined_ax=stats["candidate_avg_mined_axionite"],
            )
        )

    lines.extend(
        [
            "",
            "## Gate",
            "",
            f"- qualifies: `{gate.get('qualifies_for_promotion', False)}`",
            f"- win-rate threshold: `{gate.get('win_rate_threshold', 'n/a')}`",
            f"- avg TiEq threshold: `{gate.get('tieq_avg_threshold', 'n/a')}`",
            f"- worst TiEq threshold: `{gate.get('tieq_worst_threshold', 'n/a')}`",
            f"- failing opponents: `{', '.join(gate.get('failing_opponents', [])) or 'none'}`",
        ]
    )
    return "\n".join(lines) + "\n"


def _matrix_csv(payload: dict, destination: Path) -> None:
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "opponent",
                "games",
                "wins",
                "losses",
                "draws",
                "win_rate",
                "candidate_tieq_avg",
                "candidate_tieq_worst",
                "candidate_tled_turns",
                "candidate_builder_turns_over_0_5ms_rate",
                "candidate_builder_turns_over_1ms_rate",
                "candidate_builder_turns_over_1_5ms_rate",
                "candidate_builder_turns_over_2ms_rate",
                "win_condition_counts",
                "average_turns",
                "candidate_avg_delivered_titanium",
                "candidate_avg_delivered_refined_axionite",
                "candidate_avg_mined_titanium",
                "candidate_avg_mined_axionite",
            ]
        )
        for opponent, stats in sorted(payload["summary"].get("per_opponent", {}).items()):
            writer.writerow(
                [
                    opponent,
                    stats["games"],
                    stats["wins"],
                    stats["losses"],
                    stats["draws"],
                    stats["win_rate"],
                    stats["candidate_tieq_avg"],
                    stats["candidate_tieq_worst"],
                    stats["candidate_tled_turns"],
                    _builder_pressure_rate(stats, "0_5ms"),
                    _builder_pressure_rate(stats, "1ms"),
                    _builder_pressure_rate(stats, "1_5ms"),
                    _builder_pressure_rate(stats, "2ms"),
                    json.dumps(stats.get("win_condition_counts", {}), sort_keys=True),
                    stats["average_turns"],
                    stats["candidate_avg_delivered_titanium"],
                    stats["candidate_avg_delivered_refined_axionite"],
                    stats["candidate_avg_mined_titanium"],
                    stats["candidate_avg_mined_axionite"],
                ]
            )


def _flat_markdown(payload: dict) -> str:
    lines = [
        "# Benchmark Report",
        "",
        "| Bot | Games | Wins | Losses | Draws | Win Rate | Avg Turns |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for bot_name, stats in sorted(payload["summary"].items(), key=lambda item: (-item[1]["win_rate"], item[0])):
        lines.append(
            "| {bot} | {games} | {wins} | {losses} | {draws} | {win_rate:.1%} | {avg_turns:.1f} |".format(
                bot=bot_name,
                games=stats["games"],
                wins=stats["wins"],
                losses=stats["losses"],
                draws=stats["draws"],
                win_rate=stats["win_rate"],
                avg_turns=stats["average_turns"],
            )
        )
    return "\n".join(lines) + "\n"


def _flat_csv(payload: dict, destination: Path) -> None:
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["bot", "games", "wins", "losses", "draws", "win_rate", "average_turns"])
        for bot_name, stats in sorted(payload["summary"].items()):
            writer.writerow(
                [
                    bot_name,
                    stats["games"],
                    stats["wins"],
                    stats["losses"],
                    stats["draws"],
                    stats["win_rate"],
                    stats["average_turns"],
                ]
            )


def markdown_report(payload: dict) -> str:
    if isinstance(payload.get("summary"), dict) and "per_opponent" in payload["summary"]:
        return _matrix_markdown(payload)
    return _flat_markdown(payload)


def csv_report(payload: dict, destination: Path) -> None:
    if isinstance(payload.get("summary"), dict) and "per_opponent" in payload["summary"]:
        _matrix_csv(payload, destination)
    else:
        _flat_csv(payload, destination)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", help="Path to benchmark JSON output.")
    parser.add_argument("--markdown", default=None, help="Optional Markdown output path.")
    parser.add_argument("--csv", default=None, help="Optional CSV output path.")
    args = parser.parse_args()

    payload = load_results(Path(args.results))
    markdown = markdown_report(payload)
    if args.markdown:
        Path(args.markdown).write_text(markdown, encoding="utf-8")
    else:
        print(markdown, end="")
    if args.csv:
        csv_report(payload, Path(args.csv))


if __name__ == "__main__":
    main()
