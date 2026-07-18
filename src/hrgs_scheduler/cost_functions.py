"""
hrgs_scheduler.cost_functions
================================
Cost-function helpers for comparing and optimising purification schedules.

Formal definitions [Validated Formal Model Def, §6.1]
-----------------------------------------------------
    F(Σ; N) = w_root
        Fidelity.  The w component of the root error vector.

    R(Σ; N) = P[Σ succeeds] / E[total wall-clock time(Σ)]
        Rate.  Under renewal-theory restart on failure.

    C(Σ) = |Gen nodes in T|
        Resource cost.  Number of half-RGS copies used per trial.

    L(Σ; N) = makespan of T
        Latency.  Root node's current_time in the evaluation.

Optimisation problem [Validated Formal Model Def, §6.2]
-------------------------------------------------------
    Σ* = argmax R(Σ; N)   s.t. F(Σ; N) ≥ F_min
           over all feasible and legal Σ

The helpers in this module allow building and comparing objective values
from ``EvaluationResult`` objects, supporting all objective-substitution
variants listed in §6.3.
"""

from __future__ import annotations

from dataclasses import dataclass

from hrgs_scheduler.schedule.evaluator import EvaluationResult

# ---------------------------------------------------------------------------
# Individual extractors (thin wrappers for clarity)
# ---------------------------------------------------------------------------


def fidelity(result: EvaluationResult) -> float:
    """Return F(Σ) = w_root from an evaluation result."""
    return result.fidelity


def rate(result: EvaluationResult) -> float:
    """Return R(Σ) = success_prob / latency from an evaluation result."""
    return result.rate


def resource_cost(result: EvaluationResult) -> int:
    """Return C(Σ) = number of Gen nodes from an evaluation result."""
    return result.resource_cost


def latency(result: EvaluationResult) -> float:
    """Return L(Σ) = makespan from an evaluation result."""
    return result.latency


# ---------------------------------------------------------------------------
# Constraint checks
# ---------------------------------------------------------------------------


def satisfies_fidelity_floor(result: EvaluationResult, f_min: float) -> bool:
    """Return True when F(Σ) ≥ f_min."""
    return result.fidelity >= f_min


def satisfies_rate_floor(result: EvaluationResult, r_min: float) -> bool:
    """Return True when R(Σ) ≥ r_min."""
    return result.rate >= r_min


def satisfies_budget(result: EvaluationResult, e_max: int) -> bool:
    """Return True when C(Σ) ≤ e_max (emitter-count feasibility)."""
    return result.resource_cost <= e_max


# ---------------------------------------------------------------------------
# Objective builders
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ObjectiveConfig:
    """Configuration for the optimisation objective.

    Encodes one of the objective-substitution variants from
    [Validated Formal Model Def, §6.3]:

    Attributes
    ----------
    primary : str
        The quantity to *maximise* or *minimise*.
        One of: 'fidelity', 'rate', 'resource_cost', 'latency'.
    maximise : bool
        True → maximise primary;  False → minimise primary.
    f_min : float or None
        If set, only schedules with F(Σ) ≥ f_min are considered.
    r_min : float or None
        If set, only schedules with R(Σ) ≥ r_min are considered.
    e_max : int or None
        If set, only schedules with C(Σ) ≤ e_max are considered.
    """

    primary: str = "rate"
    maximise: bool = True
    f_min: float | None = None
    r_min: float | None = None
    e_max: int | None = None

    def is_feasible(self, result: EvaluationResult) -> bool:
        """Return True when *result* satisfies all constraints."""
        if self.f_min is not None and not satisfies_fidelity_floor(result, self.f_min):
            return False
        if self.r_min is not None and not satisfies_rate_floor(result, self.r_min):
            return False
        if self.e_max is not None and not satisfies_budget(result, self.e_max):
            return False
        return True

    def score(self, result: EvaluationResult) -> float:
        """Return the scalar score for *result* under this objective.

        Higher score is always better (negated for minimisation).
        Returns -inf for infeasible results.
        """
        if not self.is_feasible(result):
            return float("-inf")

        value: float
        if self.primary == "fidelity":
            value = fidelity(result)
        elif self.primary == "rate":
            value = rate(result)
        elif self.primary == "resource_cost":
            value = float(resource_cost(result))
        elif self.primary == "latency":
            value = latency(result)
        else:
            raise ValueError(f"Unknown primary objective: {self.primary!r}")

        return value if self.maximise else -value

    # ------------------------------------------------------------------
    # Common presets
    # ------------------------------------------------------------------

    @classmethod
    def maximize_rate_with_fidelity_floor(cls, f_min: float = 0.9) -> ObjectiveConfig:
        """Maximize R(Σ) subject to F(Σ) ≥ f_min.

        This is the primary objective from [Validated Formal Model Def, §6.2].
        The default fidelity floor F_min = 0.9 matches the paper's Fig. 5/6
        fairness constraint.
        """
        return cls(primary="rate", maximise=True, f_min=f_min)

    @classmethod
    def maximize_fidelity_with_rate_floor(cls, r_min: float) -> ObjectiveConfig:
        """Maximize F(Σ) subject to R(Σ) ≥ r_min."""
        return cls(primary="fidelity", maximise=True, r_min=r_min)

    @classmethod
    def minimize_cost_with_constraints(
        cls, f_min: float, r_min: float | None = None
    ) -> ObjectiveConfig:
        """Minimize C(Σ) subject to fidelity and optional rate floors."""
        return cls(primary="resource_cost", maximise=False, f_min=f_min, r_min=r_min)


# ---------------------------------------------------------------------------
# Comparison utility
# ---------------------------------------------------------------------------


def compare_schedules(
    results: dict[str, EvaluationResult],
    objective: ObjectiveConfig | None = None,
) -> str:
    """Format a human-readable comparison table of multiple schedule results.

    Parameters
    ----------
    results : dict[str, EvaluationResult]
        Mapping from schedule label to its evaluation result.
    objective : ObjectiveConfig or None
        If provided, also shows the feasibility and score columns.

    Returns
    -------
    str
        A plain-text table.
    """
    header = f"{'Schedule':<30} {'F':>10} {'R':>14} {'C':>5} {'L':>10} {'P_succ':>10}"
    if objective is not None:
        header += f" {'Feasible':>9} {'Score':>10}"
    lines = [header, "-" * len(header)]

    for label, res in results.items():
        row = (
            f"{label:<30} "
            f"{res.fidelity:>10.6f} "
            f"{res.rate:>14.6g} "
            f"{res.resource_cost:>5d} "
            f"{res.latency:>10.4f} "
            f"{res.success_prob:>10.6f}"
        )
        if objective is not None:
            feasible = objective.is_feasible(res)
            score = objective.score(res)
            row += f" {'Yes' if feasible else 'No':>9} {score:>10.6g}"
        lines.append(row)

    return "\n".join(lines)
