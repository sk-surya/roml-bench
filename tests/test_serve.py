"""Tests for the static-site server helpers."""

from roml_bench.serve import _local_ips, discovery_urls


def test_discovery_urls_shape():
    urls = discovery_urls(8787)
    assert urls["localhost"] == "http://127.0.0.1:8787/"
    assert isinstance(urls["lan"], list)
    assert urls["tailscale"] is None or urls["tailscale"].startswith("http://")


def test_local_ips_excludes_loopback():
    for ip in _local_ips():
        assert not ip.startswith("127.")
