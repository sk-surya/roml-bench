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
