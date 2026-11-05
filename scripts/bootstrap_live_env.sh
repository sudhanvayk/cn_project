#!/usr/bin/env bash
# One-shot bootstrap for the live Mininet + Open vSwitch testbed.
#
# Usage:
#   sudo bash scripts/bootstrap_live_env.sh
#
# Installs the system packages that cannot be installed without root. The
# project venv and the ~/ryu-env Python 3.9 controller environment are
# user-level and can be prepared separately with `make install` and the
# recipe in SETUP.md.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "[ERROR] This script must run as root: sudo bash $0" >&2
    exit 1
fi

echo "=== Installing Mininet, Open vSwitch and network utilities ==="
apt-get update
apt-get install -y mininet openvswitch-switch iproute2 traceroute python3-venv

echo "=== Enabling the Open vSwitch service ==="
if command -v systemctl >/dev/null 2>&1; then
    systemctl enable --now openvswitch-switch || true
fi

echo "=== Verification ==="
mn --version
ovs-vsctl --version | head -n 1

echo "=== Running Mininet pingall smoke test (diamond-free, 1 switch) ==="
if mn --test pingall >/tmp/mininet_pingall.log 2>&1; then
    echo "[OK] Mininet + OVS datapath is working."
else
    echo "[WARN] 'mn --test pingall' failed. Inspect /tmp/mininet_pingall.log"
    tail -n 20 /tmp/mininet_pingall.log || true
    echo "       Common fix: sudo systemctl restart openvswitch-switch"
fi

echo
echo "Next steps:"
echo "  make real-check"
echo "  make real-scenarios"
