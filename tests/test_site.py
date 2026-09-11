"""Tests for the offline site generator."""

import json
import re
from pathlib import Path

from roml_bench.site.generate import generate_site
from roml_bench.summarize import write_summary

REPO_ROOT = Path(__file__).parent.parent


def _site_run_dir(tmp_path):
    run_dir = tmp_path / "run-fixture"
    run_dir.mkdir()
    (run_dir / "run.json").write_text(json.dumps({
        "run_id": "fixture-quick", "profile": "quick", "seed": 20260908,
        "benchmark_sha": "fixture", "roml_sha": "x", "stopped": [],
    }))
    (run_dir / "environment.json").write_text(json.dumps({
        "timestamp_utc": "2026-09-08T00:00:00Z",
        "platform": "test-host",
        "python": "3.13.0",
        "cpu_model": "Test CPU",
        "memory_total_bytes": 8 * 1024**3,
        "packages": {
            "roml-python": "0.1.0", "pulp": "3.3.1", "pyomo": "6.10.1",
            "pyoptinterface": "0.6.1", "highspy": "1.15.1", "numpy": "2.0.0",
        },
    }))
    import shutil

    shutil.copy(REPO_ROOT / "fixtures" / "quick-results.jsonl", run_dir / "raw.jsonl")
    write_summary(run_dir)
    return run_dir


def test_site_generation_from_fixture(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "validation.json").write_text(
        json.dumps({"status": "ok", "implementations": {}})
    )
    out = generate_site(_site_run_dir(tmp_path), tmp_path / "site")
    for page in ("index", "python", "roml-core", "methodology", "data"):
        assert (out / f"{page}.html").is_file()
    assert (out / "static" / "plotly.min.js").is_file()
    for name in ("raw.jsonl", "summary.json", "summary.csv", "run.json",
                 "environment.json", "validation.json"):
        assert (out / "data" / name).is_file()


def test_site_has_no_cdn_dependencies(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "validation.json").write_text(json.dumps({"status": "ok"}))
    out = generate_site(_site_run_dir(tmp_path), tmp_path / "site")
    for page in ("index", "python", "roml-core", "methodology", "data"):
        html = (out / f"{page}.html").read_text()
        cdn_refs = re.findall(r'src="https?://[^"]+"|href="https?://[^"]+"', html)
        assert cdn_refs == [], (page, cdn_refs)
        assert "static/plotly.min.js" in html


def test_site_charts_use_only_measured_points(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "validation.json").write_text(json.dumps({"status": "ok"}))
    run_dir = _site_run_dir(tmp_path)
    summary = json.loads((run_dir / "summary.json").read_text())
    measured = {
        (g["workload"], g["size"], g["implementation"]) for g in summary["groups"]
    }
    out = generate_site(run_dir, tmp_path / "site")
    python_html = (out / "python.html").read_text()
    # Every plotted size label in hover text references a real group size.
    summary_sizes = {g["size"] for g in summary["groups"]}
    for size in re.findall(r"size (\d+)<", python_html):
        assert int(size) in summary_sizes
    assert measured, "fixture must contain measured groups"


def test_site_raw_data_links_resolve(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "validation.json").write_text(json.dumps({"status": "ok"}))
    out = generate_site(_site_run_dir(tmp_path), tmp_path / "site")
    for page in ("index", "python", "roml-core", "methodology", "data"):
        html = (out / f"{page}.html").read_text()
        for link in re.findall(r'href="(data/[^"]+)"', html):
            assert (out / link).is_file(), (page, link)


def _record(implementation, workload, size, median_ms, variant="canonical", replicate=0):
    return {
        "schema_version": 1,
        "run_id": "forensic",
        "timestamp_utc": "2026-09-08T00:00:00Z",
        "benchmark_sha": "forensic",
        "roml_sha": "6062398b418c4bc0c7718b2ce569da8b9e42766e",
        "implementation": implementation,
        "workload": workload,
        "size": size,
        "variables": 10,
        "constraints": 1,
        "constraint_nnz": 10,
        "objective_nnz": 10,
        "replicate": replicate,
        "seed": 20260908,
        "variant": variant,
        "container_init_ns": 1000,
        "populate_ns": int(median_ms * 1e6),
        "phases": {
            "variables": int(median_ms * 1e6 // 3),
            "constraints": int(median_ms * 1e6 // 3),
            "objective": int(median_ms * 1e6 // 3),
        },
        "rss_before_bytes": 1,
        "rss_after_bytes": 2,
        "peak_rss_bytes": 3,
        "cpu": None,
        "status": "ok",
        "error": None,
    }


def test_forensic_panels_render(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "validation.json").write_text(json.dumps({"status": "ok"}))
    run_dir = tmp_path / "run-forensic"
    run_dir.mkdir()
    (run_dir / "run.json").write_text(json.dumps({
        "run_id": "forensic", "profile": "forensic", "seed": 20260908,
        "benchmark_sha": "forensic", "roml_sha": "x", "stopped": [],
    }))
    (run_dir / "environment.json").write_text(json.dumps({
        "timestamp_utc": "2026-09-08T00:00:00Z",
        "platform": "test-host",
        "python": "3.13.0",
        "cpu_model": "Test CPU",
        "memory_total_bytes": 8 * 1024**3,
        "packages": {
            "roml-python": "0.1.0", "pulp": "3.3.1", "pyomo": "6.10.1",
            "pyoptinterface": "0.6.1", "highspy": "1.15.1", "numpy": "2.0.0",
        },
    }))
    records = []
    for impl, med in (
        ("roml_python_vectorized", 10.0), ("roml_python_naive_chain", 40.0),
        ("roml_python_csr", 12.0), ("pulp_python", 20.0), ("pyomo_python", 8.0),
        ("pyoptinterface_python", 11.0), ("pyoptinterface_scalar", 25.0),
        ("roml_core_rust", 7.0), ("roml_core_rust_anon", 5.0),
    ):
        records.append(_record(impl, "sparse_rows", 100000, med))
    records.append(_record("roml_python_vectorized", "sparse_rows", 100000, 30.0, variant="shuffled"))
    records.append(_record("roml_python_vectorized", "sparse_rows", 100000, 50.0, variant="duplicated"))
    (run_dir / "raw.jsonl").write_text("\n".join(json.dumps(r) for r in records) + "\n")
    write_summary(run_dir)
    out = generate_site(run_dir, tmp_path / "site")
    index = (out / "index.html").read_text()
    assert "Correction to the v1 report" in index
    assert "naive chain" in (out / "roml-core.html").read_text()
    data = (out / "data.html").read_text()
    assert "shuffled" in data and "Vars ms" in data
    python = (out / "python.html").read_text()
    assert "Matrix ingestion" in python and "diagnostic" in python
