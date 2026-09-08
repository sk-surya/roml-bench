"""Adapter protocol for model-build benchmark v1.

An adapter translates one canonical WorkloadCase into a modeling library's
public API. Only `populate()` runs inside the primary timer; it must not
generate workload data, import modules, solve, print, or write files.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class StructuralReport:
    implementation: str
    workload: str
    size: int
    variables: int | None
    constraints: int | None
    constraint_nnz: int | None
    objective_nnz: int | None
    # How the counts were obtained: "introspection" (library API) or
    # "construction" (exact adapter bookkeeping where the library exposes
    # no public count API). Never fabricated.
    count_source: str


@dataclass
class BuildArtifact:
    model: Any
    implementation: str
    case: Any
    variables: int
    constraints: int
    constraint_nnz: int
    objective_nnz: int


class Adapter(Protocol):
    implementation_id: str
    construction_path: str

    def warmup(self) -> None:
        """Tiny unrecorded construction to settle lazy initialization."""
        ...

    def new_model(self, case: Any) -> Any:
        """Create the empty target model/container (timed as container_init)."""
        ...

    def populate(self, model: Any, case: Any) -> BuildArtifact:
        """Build variables, constraints, and objective (primary timer)."""
        ...

    def inspect(self, artifact: BuildArtifact, case: Any) -> StructuralReport:
        """Report structural counts outside the timed path."""
        ...


def check_report_against_case(report: StructuralReport, case: Any) -> list[str]:
    """Compare available counts with the canonical case; [] when consistent."""
    problems: list[str] = []
    for field in ("variables", "constraints", "constraint_nnz", "objective_nnz"):
        got = getattr(report, field)
        want = getattr(case, field)
        if got is None:
            continue
        if got != want:
            problems.append(f"{field}: model has {got}, canonical case has {want}")
    return problems
