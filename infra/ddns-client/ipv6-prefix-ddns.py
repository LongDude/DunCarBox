#!/usr/bin/env python3
from __future__ import annotations

import ipaddress
import json
import logging
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_CONFIG = "/etc/ipv6-prefix-ddns/config.conf"
STATE_DIR = Path("/var/lib/ipv6-prefix-ddns")
STATE_FILE = STATE_DIR / "state.json"
PENDING_STATE_FILE = STATE_DIR / "pending-state.json"
CF_API_BASE = "https://api.cloudflare.com/client/v4"

log = logging.getLogger("ipv6-prefix-ddns")


@dataclass(frozen=True)
class RecordConfig:
    subdomain: str
    suffix: int
    proxied: bool


@dataclass
class Config:
    config_path: str
    interface: str
    connection: str
    cf_zone: str
    cf_zone_id: str
    cf_api_token: str
    records: list[RecordConfig]
    poll_interval: int = 5
    retry_count: int = 5
    retry_delay: int = 5
    cooldown: int = 900
    resync_interval: int = 900
    firewall_hook: str = ""


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def parse_bool(value: str) -> bool:
    value = value.strip().lower()
    if value == "true":
        return True
    if value == "false":
        return False
    raise ValueError("expected true or false")


def parse_suffix(value: str) -> int:
    value = value.strip().lower()
    if value.startswith("::"):
        value = value[2:]
    if value.startswith("0x"):
        value = value[2:]
    if not value or not re.fullmatch(r"[0-9a-f]+", value):
        raise ValueError("suffix must be hexadecimal, e.g. 10, 20, abcd or ::10")
    return int(value, 16)


def load_config(path: str) -> Config:
    values: dict[str, str] = {}
    records: list[RecordConfig] = []

    with open(path, "r", encoding="utf-8") as f:
        for lineno, raw in enumerate(f, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue

            key, sep, value = line.partition("=")
            if not sep:
                raise RuntimeError(f"{path}:{lineno}: expected KEY=VALUE")

            key = key.strip()
            value = value.strip()

            if key == "RECORD":
                parts = [part.strip() for part in value.split(",")]
                if len(parts) != 3:
                    raise RuntimeError(
                        f"{path}:{lineno}: RECORD must be "
                        "<subdomain>,<hex-suffix>,<true|false>"
                    )

                subdomain, suffix_raw, proxied_raw = parts
                if not subdomain:
                    raise RuntimeError(f"{path}:{lineno}: empty subdomain")

                try:
                    suffix = parse_suffix(suffix_raw)
                    proxied = parse_bool(proxied_raw)
                except ValueError as exc:
                    raise RuntimeError(f"{path}:{lineno}: {exc}") from exc

                records.append(RecordConfig(subdomain, suffix, proxied))
            else:
                values[key] = value

    required = [
        "INTERFACE",
        "CONNECTION",
        "CF_ZONE",
        "CF_ZONE_ID",
        "CF_API_TOKEN",
    ]
    for key in required:
        if not values.get(key):
            raise RuntimeError(f"missing required config option: {key}")

    if not records:
        raise RuntimeError("at least one RECORD must be configured")

    zone = values["CF_ZONE"].strip().rstrip(".").lower()
    if not zone:
        raise RuntimeError("CF_ZONE must not be empty")

    hostnames: set[str] = set()
    suffixes: set[int] = set()

    for record in records:
        hostname = zone if record.subdomain == "@" else f"{record.subdomain}.{zone}"
        hostname = hostname.rstrip(".").lower()

        if hostname in hostnames:
            raise RuntimeError(f"duplicate RECORD hostname: {hostname}")
        if record.suffix in suffixes:
            raise RuntimeError(
                f"duplicate RECORD IPv6 suffix: ::{record.suffix:x}"
            )

        hostnames.add(hostname)
        suffixes.add(record.suffix)

    def positive_int(name: str, default: int) -> int:
        raw = values.get(name, str(default))
        try:
            result = int(raw)
        except ValueError as exc:
            raise RuntimeError(f"{name} must be an integer") from exc
        if result <= 0:
            raise RuntimeError(f"{name} must be > 0")
        return result

    return Config(
        config_path=path,
        interface=values["INTERFACE"],
        connection=values["CONNECTION"],
        cf_zone=zone,
        cf_zone_id=values["CF_ZONE_ID"],
        cf_api_token=values["CF_API_TOKEN"],
        records=records,
        poll_interval=positive_int("POLL_INTERVAL", 5),
        retry_count=positive_int("RETRY_COUNT", 5),
        retry_delay=positive_int("RETRY_DELAY", 5),
        cooldown=positive_int("COOLDOWN", 900),
        resync_interval=positive_int("RESYNC_INTERVAL", 900),
        firewall_hook=values.get("FIREWALL_HOOK", "").strip(),
    )


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    log.debug("exec: %s", shlex.join(args))
    result = subprocess.run(
        args,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise RuntimeError(f"{shlex.join(args)} failed: {detail}")
    return result


def atomic_write_json(path: Path, data: dict[str, Any], mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def load_state() -> dict[str, Any]:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as exc:
        log.warning("cannot read %s: %s", STATE_FILE, exc)
        return {}


def get_global_addresses(interface: str) -> list[dict[str, Any]]:
    result = run(
        "ip", "-j", "-6", "addr", "show",
        "dev", interface, "scope", "global",
    )

    data = json.loads(result.stdout or "[]")
    addresses: list[dict[str, Any]] = []

    for device in data:
        for info in device.get("addr_info", []):
            if info.get("family") != "inet6" or info.get("scope") != "global":
                continue

            local = ipaddress.IPv6Address(info["local"])
            flags = set(info.get("flags", []))

            addresses.append(
                {
                    "address": local,
                    "prefixlen": int(info["prefixlen"]),
                    "dynamic": bool(info.get("dynamic", False))
                    or "dynamic" in flags,
                    "temporary": bool(info.get("temporary", False))
                    or "temporary" in flags,
                    "deprecated": bool(info.get("deprecated", False))
                    or "deprecated" in flags,
                }
            )

    return addresses


def low64(address: ipaddress.IPv6Address) -> int:
    return int(address) & ((1 << 64) - 1)


def detect_prefix(config: Config) -> tuple[ipaddress.IPv6Network, ipaddress.IPv6Address]:
    addresses = get_global_addresses(config.interface)
    managed_suffixes = {record.suffix for record in config.records}

    candidates = [
        item
        for item in addresses
        if low64(item["address"]) not in managed_suffixes
        and not item["deprecated"]
    ]

    if not candidates:
        raise RuntimeError(
            f"no non-managed global IPv6 address found on {config.interface}"
        )

    # Prefer the stable dynamic SLAAC/DHCPv6 address over temporary privacy addresses.
    preferred = [
        item for item in candidates
        if item["dynamic"] and not item["temporary"]
    ]
    if not preferred:
        preferred = [item for item in candidates if not item["temporary"]]
    if not preferred:
        preferred = candidates

    # Prefer the widest prefix if multiple non-temporary global addresses exist.
    preferred.sort(key=lambda item: item["prefixlen"])
    source = preferred[0]

    network = ipaddress.IPv6Network(
        (source["address"], source["prefixlen"]),
        strict=False,
    )

    if network.prefixlen > 64:
        log.warning(
            "detected prefix %s is longer than /64; "
            "configured hexadecimal suffixes still work if they fit",
            network,
        )

    for record in config.records:
        host_bits = 128 - network.prefixlen
        if record.suffix >= (1 << host_bits):
            raise RuntimeError(
                f"suffix ::{record.suffix:x} does not fit into {network}"
            )

    return network, source["address"]


def hostname_for(config: Config, record: RecordConfig) -> str:
    if record.subdomain == "@":
        return config.cf_zone
    return f"{record.subdomain}.{config.cf_zone}".rstrip(".").lower()


def build_records(
    config: Config,
    network: ipaddress.IPv6Network,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []

    for record in config.records:
        address = ipaddress.IPv6Address(
            int(network.network_address) + record.suffix
        )
        result.append(
            {
                "hostname": hostname_for(config, record),
                "suffix": f"{record.suffix:x}",
                "address": str(address),
                "prefixlen": network.prefixlen,
                "proxied": record.proxied,
            }
        )

    return result


def nm_configured_addresses(connection: str) -> set[str]:
    result = run(
        "nmcli", "-g", "ipv6.addresses",
        "connection", "show", connection,
    )

    raw = result.stdout.strip()
    if not raw:
        return set()

    parts = re.split(r"[,\n]+", raw)
    return {part.strip() for part in parts if part.strip()}


def expected_nm_addresses(records: list[dict[str, Any]]) -> set[str]:
    return {
        f"{record['address']}/{record['prefixlen']}"
        for record in records
    }


def verify_addresses(
    interface: str,
    records: list[dict[str, Any]],
    timeout: int = 12,
) -> None:
    expected = {
        ipaddress.IPv6Address(record["address"])
        for record in records
    }

    deadline = time.monotonic() + timeout
    last_seen: set[ipaddress.IPv6Address] = set()

    while time.monotonic() < deadline:
        last_seen = {
            item["address"]
            for item in get_global_addresses(interface)
        }
        if expected.issubset(last_seen):
            return
        time.sleep(1)

    missing = expected - last_seen
    raise RuntimeError(
        "managed IPv6 addresses did not appear on "
        f"{interface}: {', '.join(map(str, sorted(missing, key=int)))}"
    )


def configure_networkmanager(
    config: Config,
    records: list[dict[str, Any]],
) -> None:
    expected = expected_nm_addresses(records)
    current = nm_configured_addresses(config.connection)

    if current != expected:
        value = ",".join(sorted(expected))
        log.info(
            "updating NetworkManager IPv6 reservations: %s",
            value,
        )

        run(
            "nmcli", "connection", "modify",
            config.connection,
            "ipv6.method", "auto",
            "ipv6.addresses", value,
        )
    else:
        log.debug("NetworkManager IPv6 reservations already match")

    reapply = run(
        "nmcli", "device", "reapply", config.interface,
        check=False,
    )

    if reapply.returncode != 0:
        detail = reapply.stderr.strip() or reapply.stdout.strip()
        log.warning(
            "nmcli device reapply failed (%s); reactivating connection",
            detail or "unknown error",
        )
        run(
            "nmcli", "connection", "up",
            config.connection,
            "ifname", config.interface,
        )

    try:
        verify_addresses(config.interface, records)
    except RuntimeError:
        # Reapply can succeed yet a driver/NM combination may not attach the
        # changed addresses immediately. One full activation is a safe fallback.
        log.warning(
            "addresses not visible after reapply; reactivating connection %s",
            config.connection,
        )
        run(
            "nmcli", "connection", "up",
            config.connection,
            "ifname", config.interface,
        )
        verify_addresses(config.interface, records)


def cf_request(
    config: Config,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    query: dict[str, str] | None = None,
) -> dict[str, Any]:
    url = CF_API_BASE + path
    if query:
        url += "?" + urllib.parse.urlencode(query)

    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {config.cf_api_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "ipv6-prefix-ddns/1.0",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        content = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Cloudflare HTTP {exc.code}: {content}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Cloudflare request failed: {exc}") from exc

    if not result.get("success"):
        raise RuntimeError(
            f"Cloudflare API error: {result.get('errors')}"
        )

    return result


def get_dns_record(
    config: Config,
    hostname: str,
) -> dict[str, Any] | None:
    response = cf_request(
        config,
        "GET",
        f"/zones/{config.cf_zone_id}/dns_records",
        query={
            "type": "AAAA",
            "name": hostname,
        },
    )

    records = response.get("result", [])
    if not records:
        return None
    if len(records) > 1:
        raise RuntimeError(
            f"more than one AAAA record exists for {hostname}"
        )
    return records[0]


def sync_dns_record(
    config: Config,
    record: dict[str, Any],
) -> None:
    hostname = record["hostname"]
    address = record["address"]
    proxied = bool(record["proxied"])

    existing = get_dns_record(config, hostname)

    payload = {
        "type": "AAAA",
        "name": hostname,
        "content": address,
        "ttl": 1,
        "proxied": proxied,
    }

    if existing is None:
        log.info(
            "creating Cloudflare AAAA %s -> %s (proxied=%s)",
            hostname, address, str(proxied).lower(),
        )
        cf_request(
            config,
            "POST",
            f"/zones/{config.cf_zone_id}/dns_records",
            payload=payload,
        )
        return

    if (
        existing.get("content") == address
        and bool(existing.get("proxied", False)) == proxied
    ):
        log.debug(
            "Cloudflare AAAA %s already matches %s (proxied=%s)",
            hostname, address, str(proxied).lower(),
        )
        return

    log.info(
        "updating Cloudflare AAAA %s: %s -> %s (proxied=%s)",
        hostname,
        existing.get("content", "<unknown>"),
        address,
        str(proxied).lower(),
    )
    cf_request(
        config,
        "PATCH",
        f"/zones/{config.cf_zone_id}/dns_records/{existing['id']}",
        payload=payload,
    )


def make_state(
    network: ipaddress.IPv6Network,
    source_address: ipaddress.IPv6Address,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "prefix": str(network),
        "slaac_source": str(source_address),
        "records": {
            record["hostname"]: {
                "address": record["address"],
                "suffix": record["suffix"],
                "proxied": record["proxied"],
            }
            for record in records
        },
        "last_success": int(time.time()),
    }


def run_firewall_hook(
    config: Config,
    pending_state: dict[str, Any],
) -> None:

    if not config.firewall_hook:
        return

    hook = Path(config.firewall_hook)

    if not hook.is_file():
        raise RuntimeError(
            f"firewall hook does not exist: {hook}"
        )

    if not os.access(hook, os.X_OK):
        raise RuntimeError(
            f"firewall hook is not executable: {hook}"
        )

    atomic_write_json(
        PENDING_STATE_FILE,
        pending_state,
    )

    log.info(
        "running firewall hook: %s",
        hook,
    )

    run(
        str(hook),
        config.config_path,
        str(PENDING_STATE_FILE),
    )


def reconcile(
    config: Config,
    network: ipaddress.IPv6Network,
    source_address: ipaddress.IPv6Address,
) -> dict[str, Any]:
    records = build_records(config, network)

    log.info(
        "reconciling prefix %s (source=%s)",
        network,
        source_address,
    )
    for record in records:
        log.info(
            "desired record: %s -> %s (proxied=%s)",
            record["hostname"],
            record["address"],
            str(record["proxied"]).lower(),
        )

    # Never publish an address in DNS before the address exists locally.
    configure_networkmanager(config, records)

    pending_state = make_state(network, source_address, records)
    run_firewall_hook(config, pending_state)

    for record in records:
        sync_dns_record(config, record)

    final_state = make_state(network, source_address, records)
    atomic_write_json(STATE_FILE, final_state)

    try:
        PENDING_STATE_FILE.unlink()
    except FileNotFoundError:
        pass

    log.info("synchronization completed successfully for %s", network)
    return final_state


def main(config_path: str) -> int:
    setup_logging()
    config = load_config(config_path)
    state = load_state()

    last_successful_prefix = state.get("prefix")
    last_sync = float(state.get("last_success", 0))

    # Always reconcile once after daemon start. This catches config changes,
    # deleted local addresses and manually modified DNS records immediately.
    force_reconcile = True

    cooldown_prefix: str | None = None
    cooldown_until = 0.0

    log.info(
        "started: interface=%s connection=%s zone=%s records=%d",
        config.interface,
        config.connection,
        config.cf_zone,
        len(config.records),
    )

    while True:
        try:
            network, source_address = detect_prefix(config)
            prefix = str(network)
            now = time.time()

            if (
                not force_reconcile
                and cooldown_prefix == prefix
                and now < cooldown_until
            ):
                time.sleep(config.poll_interval)
                continue

            prefix_changed = prefix != last_successful_prefix
            periodic_resync = (now - last_sync) >= config.resync_interval

            if not (force_reconcile or prefix_changed or periodic_resync):
                time.sleep(config.poll_interval)
                continue

            if prefix_changed:
                log.info(
                    "IPv6 prefix change detected: %s -> %s",
                    last_successful_prefix or "<unknown>",
                    prefix,
                )
            elif force_reconcile:
                log.info("initial reconciliation for prefix %s", prefix)
            else:
                log.info("periodic reconciliation for prefix %s", prefix)

            success = False

            for attempt in range(1, config.retry_count + 1):
                try:
                    # Re-read the prefix on every attempt because PPPoE/RA may
                    # have changed again while we were retrying.
                    network, source_address = detect_prefix(config)
                    prefix = str(network)

                    new_state = reconcile(
                        config,
                        network,
                        source_address,
                    )

                    last_successful_prefix = new_state["prefix"]
                    last_sync = float(new_state["last_success"])
                    success = True
                    break

                except Exception:
                    log.exception(
                        "synchronization attempt %d/%d failed",
                        attempt,
                        config.retry_count,
                    )
                    if attempt < config.retry_count:
                        time.sleep(config.retry_delay)

            force_reconcile = False

            if success:
                cooldown_prefix = None
                cooldown_until = 0.0
            else:
                cooldown_prefix = prefix
                cooldown_until = time.time() + config.cooldown
                log.error(
                    "all %d attempts failed for %s; cooldown for %d seconds",
                    config.retry_count,
                    prefix,
                    config.cooldown,
                )

        except Exception:
            log.exception("service loop failed")

        time.sleep(config.poll_interval)


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CONFIG
    try:
        raise SystemExit(main(path))
    except KeyboardInterrupt:
        raise SystemExit(0)
    except Exception:
        setup_logging()
        log.exception("fatal service error")
        raise SystemExit(1)
