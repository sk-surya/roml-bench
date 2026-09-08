# Performance milestone close (P0–P2A) — canonical record

Date: 2026-09-08. Status: finished. No further synthetic optimization;
next performance work triggers off real-model profiles.

## Canonical pointers

- `main` @ `c88105a0b19319e5670c77946e2f8489bbeb34aa`
  (merge of #55; tree `0f258bd…370fd`, byte-identical to the CI-tested head).
- Certified code: `9cea164` + comment-only CI markers (`788b94c`).
- Certification evidence (immutable): this repo @ `a3605695`,
  run `results/runs/20260908T224657Z-ai90-a2f016a7/`,
  report `results/research/p0-objective/FINAL_CERTIFICATION.md`.
- Baseline: ROML `6062398`.

## Canonical results (7-rep forensic medians)

Sparse 1M: Python bulk 155.3 ms · core bulk 155.6 ms (1.00x) ·
Pyomo 1067.6 ms (6.9x) · POI scalar 1112.4 ms · POI matrix 1642.6 ms ·
PuLP 2069.1 ms.
BESS300: idiomatic 26.7 ms (4.8x vs POI scalar, 12.7x vs Pyomo) ·
CSR 25.7 ms · core bulk 16.2 ms · POI scalar 129.4 ms ·
POI matrix 217.2 ms · Pyomo 339.6 ms · PuLP 488.5 ms.

Do not replace these numbers without a recertification run.

## Post-merge close-out (separate, non-recertifying)

- Flaky heartbeat CI test redesigned deterministically (ROMl PR
  follow-up; larger solve window + beat-count and gap assertions with
  orders-of-magnitude margins instead of two 1 ms ticks).
- `MIGRATION.md`: P1C-2 additive APIs listed.
