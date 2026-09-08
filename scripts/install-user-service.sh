#!/usr/bin/env bash
# Install and start roml-bench-site.service as a user-level systemd unit.
# Serves the generated ./site directory on 0.0.0.0:8787. Never requires root.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT="$UNIT_DIR/roml-bench-site.service"
PORT="${ROML_BENCH_PORT:-8787}"

mkdir -p "$UNIT_DIR"
cat > "$UNIT" <<EOF
[Unit]
Description=ROML model-build benchmark report site
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$REPO
ExecStart=$REPO/.venv/bin/roml-bench serve --host 0.0.0.0 --port $PORT --directory $REPO/site
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now roml-bench-site.service
systemctl --user is-active roml-bench-site.service
