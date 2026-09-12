"""Exercise installer ordering and failure handling without running sudo."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


INSTALLER = Path(__file__).resolve().parents[2] / "ddns-client/install.sh"


class InstallerTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.log = self.root / "calls.jsonl"
        self.config = self.root / "custom config.conf"
        self.config.write_text("INTERFACE=eth0\nCONNECTION=test\nCF_ZONE=example.com\n"
                               "CF_ZONE_ID=zone\nCF_API_TOKEN=dummy\nRECORD=app,10,false\n")
        sudo = self.root / "sudo"
        sudo.write_text("#!/usr/bin/env python3\nimport json, os, sys\n"
                        "with open(os.environ['INSTALL_LOG'], 'a') as stream:\n"
                        "    stream.write(json.dumps(sys.argv[1:]) + '\\n')\n"
                        "sys.exit(1 if os.environ.get('INSTALL_FAIL') == '1' else 0)\n")
        sudo.chmod(0o700)
        self.env = {**os.environ, "PATH": str(self.root) + os.pathsep + os.environ["PATH"],
                    "INSTALL_LOG": str(self.log)}

    def install(self):
        return subprocess.run(["bash", str(INSTALLER), str(self.config)], cwd=self.root,
                              env=self.env, capture_output=True, text=True)

    def test_install_works_outside_script_directory_and_enables_service(self):
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertIn(["install", "-m", "0600", str(self.config), "/etc/ipv6-prefix-ddns/config.conf"], calls)
        self.assertIn(["systemctl", "enable", "ipv6-prefix-ddns.service"], calls)
        self.assertIn(["systemctl", "restart", "ipv6-prefix-ddns.service"], calls)

    def test_privileged_failure_stops_before_restart(self):
        self.env["INSTALL_FAIL"] = "1"
        self.assertNotEqual(self.install().returncode, 0)
        self.assertEqual(len(self.log.read_text().splitlines()), 1)

    def test_invalid_config_rejected_before_privileged_operations(self):
        self.config.write_text("INTERFACE=eth0\n")
        self.assertNotEqual(self.install().returncode, 0)
        self.assertFalse(self.log.exists())


if __name__ == "__main__":
    unittest.main()
