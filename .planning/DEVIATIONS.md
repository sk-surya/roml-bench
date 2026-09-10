# Deviations

No deviations are recorded in the planning baseline.

During execution, append only deviations that materially change a locked package pin, benchmark boundary, workload mathematics, runtime-control assumption, serving mechanism, or acceptance gate. Each entry must state the reason, evidence, and effect on interpretation.

## Forensic pass corrections (2026-09-08, owner review of v1 run)

These are methodology corrections, not contract violations: the v1
contract's timed boundary, canonical-input rule, and panels stand; the
forensic pass fixes adapter paths that did not represent the documented
efficient public API, and splits one conflated leaderboard into two
honest panels.

1. **BESS ROML bulk objective fused into one `rm.dot` call** (was a Python
   loop chaining growing expressions, O(B^2)-ish; B=300 fell 606 ms to
   197 ms). Reason: the loop was never the efficient public path.
   `rm.dot` over a precomputed contiguous price grid is. Evidence:
   forensic run + validation-gate cross-solver agreement unchanged.
   Effect: v1 BESS ROML numbers are superseded, not comparable.
2. **Scalar arm renamed `roml_python_scalar` → `roml_python_naive_chain`.**
   Reason: `total = total + v` chaining is O(n^2) (clone + linear scan per
   `+`, verified in ROML source); the v1 "350x binding overhead" claim is
   retracted. Old ID remains accepted for historical raw files only.
3. **Formulation vs matrix-ingestion panel split.** Reason: v1 timed POI
   matrix ingestion of preassembled CSR against ROML algebra formulation
   on BESS. New arms: `roml_python_csr` (bess CSR ingestion),
   `pyoptinterface_scalar` (formulation without shared CSR),
   `roml_core_rust_anon` (isolates name registration). Per-arm workload
   support and variant-scoped stop keys recorded in run.json.
4. **POI matrix path cannot ingest duplicate CSR entries** (HiGHS rejects
   duplicate indices, Status -1). Reason: discovered by the duplicated
   diagnostic variant, not a benchmark error. Effect: duplicated variant
   has no POI points; ROML bulk shows no measurable duplicate penalty.
