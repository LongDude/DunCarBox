#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
config_file="${1:-$script_dir/config.conf}"
[[ -r "$config_file" ]] || { echo "Config not readable: $config_file" >&2; exit 1; }
# Import and validate without running reconciliation or printing the API token.
python3 - "$script_dir/ipv6-prefix-ddns.py" "$config_file" <<'PY'
import importlib.util
import sys
spec = importlib.util.spec_from_file_location("ddns_install", sys.argv[1])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
module.load_config(sys.argv[2])
PY

sudo install -d -m 0700 /etc/ipv6-prefix-ddns /var/lib/ipv6-prefix-ddns
sudo install -m 0750 "$script_dir/ipv6-prefix-ddns.py" /usr/local/sbin/ipv6-prefix-ddns
sudo install -m 0750 "$script_dir/ipv6-prefix-ddns-firewall" /usr/local/sbin/ipv6-prefix-ddns-firewall
sudo install -m 0600 "$config_file" /etc/ipv6-prefix-ddns/config.conf
sudo install -m 0644 "$script_dir/ipv6-prefix-ddns.service" /etc/systemd/system/ipv6-prefix-ddns.service
sudo systemctl daemon-reload
sudo systemctl enable ipv6-prefix-ddns.service
sudo systemctl restart ipv6-prefix-ddns.service
sudo journalctl -u ipv6-prefix-ddns.service -n 40 --no-pager
