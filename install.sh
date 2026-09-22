#!/usr/bin/env bash
# install.sh - install sysadmin-agent as a systemd service.
#
# Usage (as root):
#   sudo ./install.sh            # install + enable + start
#   sudo ./install.sh --uninstall
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "error: root required" >&2; exit 1; }

APP_NAME="sysadmin-agent"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="/opt/${APP_NAME}"
CONF_DIR="/etc/${APP_NAME}"
UNIT_FILE="/etc/systemd/system/${APP_NAME}.service"

if [[ "${1:-}" == "--uninstall" ]]; then
    systemctl stop "$APP_NAME" 2>/dev/null || true
    systemctl disable "$APP_NAME" 2>/dev/null || true
    rm -f "$UNIT_FILE"
    rm -rf "$INSTALL_DIR"
    systemctl daemon-reload
    echo "uninstalled (config kept in $CONF_DIR)"
    exit 0
fi

echo "==> installing to $INSTALL_DIR"
mkdir -p "$INSTALL_DIR" "$CONF_DIR"
cp -r "$SRC_DIR/agent" "$SRC_DIR/bin" "$SRC_DIR/requirements.txt" "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR"/bin/*.sh

# config: never overwrite an existing one
if [[ ! -f "$CONF_DIR/config.yaml" ]]; then
    install -m 644 "$SRC_DIR/config/config.yaml" "$CONF_DIR/config.yaml"
    echo "    default config installed to $CONF_DIR/config.yaml"
else
    echo "    keeping existing $CONF_DIR/config.yaml"
fi

echo "==> installing python dependencies"
python3 -m pip install --quiet -r "$SRC_DIR/requirements.txt" || \
    echo "    warning: pip failed, make sure psutil and PyYAML are installed"

echo "==> installing systemd unit"
install -m 644 "$SRC_DIR/systemd/sysadmin-agent.service" "$UNIT_FILE"
systemctl daemon-reload
systemctl enable "$APP_NAME"

echo "==> starting $APP_NAME"
systemctl restart "$APP_NAME"
sleep 2
systemctl --no-pager --lines=0 status "$APP_NAME" || true

cat <<EOF

Done.

  start:   systemctl start $APP_NAME
  stop:    systemctl stop $APP_NAME
  status:  systemctl status $APP_NAME
  logs:    journalctl -u $APP_NAME -f
  config:  $CONF_DIR/config.yaml   (edit, then: systemctl restart $APP_NAME)

IMPORTANT: config ships with dry_run: true (alerts only).
Set dry_run: false in $CONF_DIR/config.yaml to allow
drop_caches / log deletion / iptables bans.
EOF
