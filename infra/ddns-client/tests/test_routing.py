"""Real kernel tests, run only in a disposable user/network namespace:

unshare --user --map-root-user --net env DDNS_NETWORK_TESTS=1 \
    python3 -m unittest discover -s infra/ddns-client/tests -p test_routing.py -v
"""
import ipaddress
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from test_config import ddns


@unittest.skipUnless(
    os.environ.get("DDNS_NETWORK_TESTS") == "1" and os.geteuid() == 0
    and Path("/proc/self/uid_map").read_text().split()[-1] == "1",
    "requires isolated user/network namespace",
)
class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.network = ipaddress.IPv6Network("2001:db8:1::/64")
        self.config = ddns.Config(
            config_path="unused", interface="eth0", connection="test",
            cf_zone="example.test", cf_zone_id="test", cf_api_token="test",
            records=[ddns.RecordConfig("app", 0x10, False),
                     ddns.RecordConfig("proxy", 0x10, True),
                     ddns.RecordConfig("ssh", 0x20, False),
                     ddns.RecordConfig("other", 0x30, False)],
            direct_routing=True,
        )
        self.ip("link", "add", "eth0", "type", "dummy")
        self.ip("link", "add", "happ-xray", "type", "dummy")
        for dev in ("lo", "eth0", "happ-xray"):
            self.ip("link", "set", dev, "up")
        for address in ("fe80::2/64", "2001:db8:1::1234/64", "2001:db8:1::10/64",
                        "2001:db8:1::20/64", "2001:db8:1::30/64"):
            self.ip("-6", "addr", "add", address, "dev", "eth0", "nodad")
        self.ip("-6", "route", "add", "default", "via", "fe80::1", "dev", "eth0",
                "proto", "ra", "metric", "100")
        self.ip("-6", "route", "add", "default", "dev", "happ-xray", "metric", "1")

    def tearDown(self):
        for rule in json.loads(self.ip("-j", "-6", "rule", "show")):
            if rule["priority"] not in (0, 32766):
                self.ip("-6", "rule", "del", "priority", str(rule["priority"]))
        self.ip("-6", "route", "flush", "table", "106")
        self.ip("link", "del", "eth0")
        self.ip("link", "del", "happ-xray")

    def ip(self, *args):
        return ddns.run("ip", *args).stdout

    def route(self, source, destination="2001:db8:ffff::1"):
        return json.loads(self.ip("-j", "-6", "route", "get", destination, "from", source))[0]

    def apply(self):
        ddns.configure_direct_routing(self.config, self.network)

    def test_only_two_sources_bypass_happ_and_local_route_still_wins(self):
        main_before = self.ip("-j", "-6", "route", "show", "table", "main")
        self.apply()
        for suffix in ("10", "20"):
            route = self.route("2001:db8:1::" + suffix)
            self.assertEqual(route["dev"], "eth0")
            self.assertEqual(route["gateway"], "fe80::1")
        for suffix in ("30", "1234"):
            self.assertEqual(self.route("2001:db8:1::" + suffix)["dev"], "happ-xray")
        self.assertEqual(self.route("2001:db8:1::10", "2001:db8:1::20")["type"], "local")
        lan = self.route("2001:db8:1::10", "2001:db8:1::abcd")
        self.assertEqual(lan["dev"], "eth0")
        self.assertNotIn("gateway", lan)
        self.assertEqual(main_before, self.ip("-j", "-6", "route", "show", "table", "main"))

    def test_repeated_poll_does_not_mutate_routes_or_duplicate_rules(self):
        self.apply()
        with patch.object(ddns, "run", wraps=ddns.run) as run:
            self.apply()
        self.assertFalse(any(set(call.args) & {"add", "del", "replace", "flush"}
                             for call in run.call_args_list))
        rules = json.loads(self.ip("-j", "-6", "rule", "show"))
        self.assertEqual(len([r for r in rules if str(r.get("table")) == "106"]), 2)

    def test_prefix_change_replaces_exceptions(self):
        self.apply()
        self.network = ipaddress.IPv6Network("2001:db8:2::/64")
        for suffix in ("10", "20"):
            self.ip("-6", "addr", "add", f"2001:db8:2::{suffix}/64", "dev", "eth0", "nodad")
        self.apply()
        self.assertEqual(self.route("2001:db8:2::10")["dev"], "eth0")
        self.assertEqual(self.route("2001:db8:1::10")["dev"], "happ-xray")
        self.assertNotIn("2001:db8:1::/64", self.ip("-6", "route", "show", "table", "106"))

    def test_gateway_loss_blocks_fallback_and_recovers_with_new_gateway(self):
        self.apply()
        self.ip("-6", "route", "del", "default", "dev", "eth0")
        with self.assertRaisesRegex(RuntimeError, "no physical IPv6 default gateway"):
            self.apply()
        with self.assertRaisesRegex(RuntimeError, "Network is unreachable|No route to host"):
            self.route("2001:db8:1::10")
        self.assertEqual(self.route("2001:db8:1::1234")["dev"], "happ-xray")
        self.ip("-6", "route", "add", "default", "via", "fe80::3", "dev", "eth0", "metric", "100")
        self.apply()
        self.assertEqual(self.route("2001:db8:1::20")["gateway"], "fe80::3")

    def test_happ_restart_and_disabling_exceptions(self):
        self.apply()
        self.ip("-6", "route", "del", "default", "dev", "happ-xray")
        self.ip("-6", "route", "add", "default", "dev", "happ-xray", "metric", "1")
        self.apply()
        self.assertEqual(self.route("2001:db8:1::10")["dev"], "eth0")
        self.config.direct_routing = False
        self.apply()
        self.assertEqual(self.route("2001:db8:1::10")["dev"], "happ-xray")
        self.assertEqual(json.loads(self.ip("-j", "-6", "route", "show", "table", "106")), [])

    def test_foreign_table_is_not_overwritten(self):
        self.ip("-6", "route", "add", "default", "dev", "happ-xray", "table", "106")
        before = self.ip("-j", "-6", "route", "show", "table", "106")
        with self.assertRaisesRegex(RuntimeError, "already used"):
            self.apply()
        self.assertEqual(before, self.ip("-j", "-6", "route", "show", "table", "106"))

    def test_higher_priority_foreign_rule_is_not_overwritten(self):
        self.ip("-6", "rule", "add", "priority", "50", "table", "main")
        before = self.ip("-j", "-6", "rule", "show")
        with self.assertRaisesRegex(RuntimeError, "priorities"):
            self.apply()
        self.assertEqual(before, self.ip("-j", "-6", "rule", "show"))
