import importlib.util
import ipaddress
from pathlib import Path
import sys
import tempfile
import unittest


spec = importlib.util.spec_from_file_location(
    "ipv6_prefix_ddns", Path(__file__).resolve().parents[1] / "ipv6-prefix-ddns.py"
)
ddns = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = ddns
spec.loader.exec_module(ddns)


class SharedSuffixTests(unittest.TestCase):
    def load_config(self, records):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.conf"
            path.write_text(
                "INTERFACE=eth0\nCONNECTION=test\nCF_ZONE=example.ru\n"
                "CF_ZONE_ID=test-zone\nCF_API_TOKEN=test-token\n" + records,
                encoding="utf-8",
            )
            return ddns.load_config(str(path))

    def test_shared_suffix_preserves_each_record_and_deduplicates_local_address(self):
        network = ipaddress.IPv6Network("2001:db8::/64")
        for first, second in [(True, False), (False, True), (True, True), (False, False)]:
            with self.subTest(first=first, second=second):
                config = self.load_config(
                    f"RECORD=app,10,{str(first).lower()}\n"
                    f"RECORD=direct,::10,{str(second).lower()}\n"
                )
                records = ddns.build_records(config, network)
                state = ddns.make_state(
                    network, ipaddress.IPv6Address("2001:db8::1234"), records
                )
                self.assertEqual(
                    state["records"],
                    {
                        hostname: {
                            "address": "2001:db8::10", "suffix": "10", "proxied": proxied
                        }
                        for hostname, proxied in [
                            ("app.example.ru", first), ("direct.example.ru", second)
                        ]
                    },
                )
                self.assertEqual(ddns.expected_nm_addresses(records), {"2001:db8::10/64"})

    def test_duplicate_hostname_still_rejected(self):
        for record in ["app,10,true", "APP,10,false", "app,20,true"]:
            with self.subTest(record=record):
                with self.assertRaisesRegex(RuntimeError, "duplicate RECORD hostname"):
                    self.load_config(f"RECORD=app,10,true\nRECORD={record}\n")


if __name__ == "__main__":
    unittest.main()
