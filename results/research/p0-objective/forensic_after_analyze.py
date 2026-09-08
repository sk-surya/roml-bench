"""AFTER analysis for the P0..P1C2 forensic pass. Usage: analyze.py <run_dir>"""
import json
import statistics
import sys

RUN = sys.argv[1]
recs = [json.loads(l) for l in open(f"{RUN}/raw.jsonl")]
meta = json.load(open(f"{RUN}/run.json"))
print("run:", meta["run_id"], "profile:", meta["profile"], "roml:", meta["roml_sha"])
print("total records:", len(recs))
ok = [r for r in recs if r["status"] == "ok"]
print("ok:", len(ok), "non-ok:", len(recs) - len(ok))
for r in recs:
    if r["status"] != "ok":
        print("NON-OK:", r["implementation"], r["workload"], r["size"],
              r["status"], (r.get("error") or "")[:100])


def canon(workload, size, impl):
    return [r for r in ok if r["workload"] == workload and r["size"] == size
            and r["implementation"] == impl and r.get("variant", "canonical") == "canonical"]


def med(vals):
    return round(statistics.median(vals), 1) if vals else None


print("\n=== headline medians (populate ms) ===")
for workload, size in [("sparse_rows", 1_000_000), ("bess_96", 300)]:
    print(f"--- {workload} {size} ---")
    impls = sorted({r["implementation"] for r in ok
                    if r["workload"] == workload and r["size"] == size})
    for impl in impls:
        g = canon(workload, size, impl)
        print(f"  {impl:24} n={len(g)} med={med([r['populate_ns'] / 1e6 for r in g])}")

print("\n=== scaling curves (median populate ms) ===")
for workload, sizes in [("sparse_rows", [10_000, 100_000, 300_000, 1_000_000]),
                        ("bess_96", [10, 30, 100, 300])]:
    print(f"--- {workload} ---")
    impls = sorted({r["implementation"] for r in ok if r["workload"] == workload})
    print("size      " + "".join(f"{i:>22}" for i in impls))
    for s in sizes:
        row = []
        for impl in impls:
            g = canon(workload, s, impl)
            m = med([r["populate_ns"] / 1e6 for r in g])
            row.append(f"{m if m is not None else 'STOPPED':>22}")
        print(f"{s:<10}" + "".join(row))

print("\n=== ROML phase transformation (median ms + peak RSS MB) ===")
for workload, size in [("sparse_rows", 1_000_000), ("bess_96", 300)]:
    for impl in ["roml_python_bulk", "roml_python_csr"]:
        g = canon(workload, size, impl)
        if not g:
            continue
        print(f"--- {impl} {workload} {size} n={len(g)} ---")
        for ph in ["variables", "constraints", "objective"]:
            vals = [r["phases"][ph] / 1e6 for r in g if "phases" in r and ph in r["phases"]]
            print(f"  {ph}: {med(vals)}")
        print(f"  total: {med([r['populate_ns'] / 1e6 for r in g])}")
        print(f"  peakRSS: {med([r['peak_rss_bytes'] / 1e6 for r in g])}")
