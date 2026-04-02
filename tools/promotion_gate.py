"""Helpers for staged promotion and active-flow rejection decisions."""

from __future__ import annotations

from dataclasses import dataclass

from tools.benchmark_matrix import MAX_REMEDIATION_ROUNDS


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    candidate: str
    qualifies: bool
    remediation_round: int
    recommendation: str
    reason: str


def decide_promotion(candidate: str, gate: dict, remediation_round: int) -> PromotionDecision:
    if gate.get("qualifies_for_promotion", False):
        return PromotionDecision(
            candidate=candidate,
            qualifies=True,
            remediation_round=remediation_round,
            recommendation="promote",
            reason="Candidate meets the per-opponent win-rate and TiEq thresholds in the studied set.",
        )

    failing = gate.get("failing_opponents", [])
    if remediation_round < 1:
        return PromotionDecision(
            candidate=candidate,
            qualifies=False,
            remediation_round=remediation_round,
            recommendation="remediate_round_1",
            reason=(
                "Initial gate failed. Run replay diagnosis and targeted strategy repair against "
                f"these opponents: {', '.join(failing) if failing else 'unknown'}."
            ),
        )
    if remediation_round < MAX_REMEDIATION_ROUNDS:
        return PromotionDecision(
            candidate=candidate,
            qualifies=False,
            remediation_round=remediation_round,
            recommendation="remediate_round_2",
            reason=(
                "Second attempt required. Tighten the weakest per-opponent win-rate or TiEq results "
                f"against: {', '.join(failing) if failing else 'unknown'}."
            ),
        )
    return PromotionDecision(
        candidate=candidate,
        qualifies=False,
        remediation_round=remediation_round,
        recommendation="deactivate_from_active_flow",
        reason=(
            "Gate still failing after two remediation rounds with no clear recovery; remove the "
            "candidate from the active promotion flow."
        ),
    )
