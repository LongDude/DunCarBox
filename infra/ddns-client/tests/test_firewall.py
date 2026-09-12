"""Packet-level checks of the hook in a disposable user/network namespace."""
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest


@unittest.skipUnless(
    os.environ.get("DDNS_NETWORK_TESTS") == "1" and os.geteuid() == 0
    and Path("/proc/self/uid_map").read_text().split()[-1] == "1",
    "requires isolated user/network namespace",
)
class FirewallTests(unittest.TestCase):
    def run_command(self, *args):
        return subprocess.run(args, check=True, text=True, capture_output=True).stdout

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "logger").write_text("#!/bin/sh\nexit 0\n")
        (self.root / "logger").chmod(0o755)
        self.peer = subprocess.Popen(
            ["unshare", "--net", "python3", "-c",
             "import sys; print('ready', flush=True); sys.stdin.read()"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
        )
        self.addCleanup(self.stop_peer)
        self.assertEqual(self.peer.stdout.readline().strip(), "ready")
        self.run_command("ip", "link", "add", "eth0", "type", "veth", "peer", "name", "peer0")
        self.addCleanup(self.run_command, "ip", "link", "del", "eth0")
        self.run_command("ip", "link", "set", "peer0", "netns", str(self.peer.pid))
        self.run_command("ip", "link", "set", "eth0", "up")
        for suffix in ("10", "20", "30"):
            self.run_command("ip", "-6", "addr", "add", f"2001:db8::{suffix}/64",
                             "dev", "eth0", "nodad")
        self.in_peer("ip", "link", "set", "peer0", "up")
        self.in_peer("ip", "-6", "addr", "add", "2001:db8::2/64", "dev", "peer0", "nodad")
        for chain in ("INPUT", "FORWARD", "OUTPUT"):
            self.run_command("ip6tables", "-P", chain, "ACCEPT")
        self.run_command("ip6tables", "-F")
        self.run_command("ip6tables", "-X")
        self.addCleanup(self.reset_firewall)
        self.run_command("ip6tables", "-N", "ufw6-user-input")
        self.run_command("ip6tables", "-P", "INPUT", "DROP")
        self.run_command("ip6tables", "-P", "FORWARD", "DROP")
        self.run_command("ip6tables", "-A", "INPUT", "-m", "conntrack", "--ctstate",
                         "ESTABLISHED,RELATED", "-j", "ACCEPT")
        self.run_command("ip6tables", "-A", "INPUT", "-p", "ipv6-icmp", "-j", "ACCEPT")
        self.run_command("ip6tables", "-A", "INPUT", "-j", "ufw6-user-input")
        for port in (80, 443, 42, 22, 8080):
            listener = socket.socket(socket.AF_INET6)
            self.addCleanup(listener.close)
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("::", port))
            listener.listen(16)
        (self.root / "config.conf").write_text("INTERFACE=eth0\n")
        (self.root / "state.json").write_text(json.dumps({"records": {
            "app": {"suffix": "10", "address": "2001:db8::10"},
            "ssh": {"suffix": "20", "address": "2001:db8::20"},
        }}))

    def stop_peer(self):
        self.peer.stdin.close()
        self.peer.wait(timeout=5)
        self.peer.stdout.close()

    def reset_firewall(self):
        for chain in ("INPUT", "FORWARD", "OUTPUT"):
            self.run_command("ip6tables", "-P", chain, "ACCEPT")
        self.run_command("ip6tables", "-F")
        self.run_command("ip6tables", "-X")

    def in_peer(self, *args):
        return self.run_command("nsenter", "-t", str(self.peer.pid), "-n", *args)

    def apply(self):
        hook = Path(__file__).resolve().parents[1] / "ipv6-prefix-ddns-firewall"
        return subprocess.run(
            ["bash", str(hook), str(self.root / "config.conf"), str(self.root / "state.json")],
            env={**os.environ, "PATH": str(self.root) + ":" + os.environ["PATH"]},
            text=True, capture_output=True,
        )

    def connects(self, suffix, port):
        result = subprocess.run(
            ["nsenter", "-t", str(self.peer.pid), "-n", "python3", "-c",
             "import socket,sys; socket.create_connection((sys.argv[1],int(sys.argv[2])),.5).close()",
             "2001:db8::" + suffix, str(port)], capture_output=True,
        )
        return result.returncode == 0

    def test_only_service_ports_pass_ufw_and_reload_restores_exceptions(self):
        result = self.apply()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for suffix, port in (("10", 80), ("10", 443), ("20", 42)):
            self.assertTrue(self.connects(suffix, port))
        for suffix, port in (("10", 42), ("20", 80), ("20", 22), ("10", 8080), ("30", 80)):
            self.assertFalse(self.connects(suffix, port))
        self.assertIn("IPV6-DDNS-DOCKER", self.run_command("ip6tables", "-S", "FORWARD"))
        self.run_command("ip6tables", "-F", "ufw6-user-input")
        self.assertFalse(self.connects("10", 80))
        self.assertEqual(self.apply().returncode, 0)
        self.assertEqual(self.apply().returncode, 0)
        self.assertTrue(self.connects("10", 80))
        rules = self.run_command("ip6tables", "-S", "ufw6-user-input")
        self.assertEqual(rules.count("-j IPV6-DDNS-ALLOW"), 1)
        self.assertEqual(self.run_command("ip6tables", "-S", "OUTPUT").strip(), "-P OUTPUT ACCEPT")

    def test_explicit_ufw_deny_precedes_dynamic_allow(self):
        self.run_command("ip6tables", "-A", "ufw6-user-input", "-d", "2001:db8::10",
                         "-p", "tcp", "--dport", "80", "-j", "REJECT")
        self.assertEqual(self.apply().returncode, 0)
        self.assertFalse(self.connects("10", 80))
        self.assertTrue(self.connects("10", 443))

    def test_missing_ufw_fails_before_creating_any_allow(self):
        self.run_command("ip6tables", "-F", "INPUT")
        self.run_command("ip6tables", "-X", "ufw6-user-input")
        result = self.apply()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("active UFW", result.stdout)
        self.assertNotIn("IPV6-DDNS", self.run_command("ip6tables", "-S"))

    def test_native_docker_chain_is_used_when_present(self):
        self.run_command("ip6tables", "-N", "DOCKER-USER")
        self.assertEqual(self.apply().returncode, 0)
        self.assertIn("IPV6-DDNS-DOCKER", self.run_command("ip6tables", "-S", "DOCKER-USER"))
        self.assertNotIn("IPV6-DDNS-DOCKER", self.run_command("ip6tables", "-S", "FORWARD"))
