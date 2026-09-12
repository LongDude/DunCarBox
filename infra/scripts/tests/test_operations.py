import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location("operations", Path(__file__).resolve().parents[1] / "operations.py")
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)


class OperationsTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        infra = self.root / "infra/k3d-infra"
        infra.mkdir(parents=True)
        for name, value in {"ROOT": self.root, "INFRA": infra,
                            "PLAN": infra / "deploy.tfplan",
                            "PLAN_META": infra / "deploy.tfplan.meta.json",
                            "LOCAL_CONFIG": infra / "zz-operations.auto.tfvars.json"}.items():
            mock = patch.object(ops, name, value)
            mock.start()
            self.addCleanup(mock.stop)
        self.config = {"registry_host_port": "5000", "tags": {"backend": "old-back", "frontend": "old-front"},
                       "cluster_name": "test", "kubeconfig_path": "~/.kube/config",
                       "ingress_host": "app.example.com"}

    def candidate(self, component="backend"):
        data = {"tag": "new-build", "image": f"localhost:5000/duncarbox-{component}:new-build", "id": "sha256:123"}
        ops.atomic_write(ops.built_path(component), json.dumps(data))
        return data

    def test_failed_push_keeps_both_published_tags(self):
        self.candidate()
        for component in ops.COMPONENTS:
            ops.atomic_write(ops.tag_path(component), "old-" + component)

        def execute(*args, **kwargs):
            if args[:2] == ("docker", "push"):
                raise RuntimeError("registry unavailable")
            return subprocess.CompletedProcess(args, 0, "sha256:123\n", "")

        with patch.object(ops, "run", side_effect=execute):
            with self.assertRaisesRegex(RuntimeError, "registry unavailable"):
                ops.push_image("backend", self.config)
        for component in ops.COMPONENTS:
            self.assertEqual(ops.tag_path(component).read_text(), "old-" + component)

    def test_successful_push_changes_only_selected_component(self):
        self.candidate()
        ops.atomic_write(ops.tag_path("frontend"), "frontend-stable\n")
        with patch.object(ops, "run", return_value=subprocess.CompletedProcess([], 0, "sha256:123\n", "")) as execute:
            ops.push_image("backend", self.config)
        self.assertEqual(ops.tag_path("backend").read_text(), "new-build\n")
        self.assertEqual(ops.tag_path("frontend").read_text(), "frontend-stable\n")
        self.assertEqual(execute.call_args_list[-1].args[:2], ("docker", "push"))

    def test_build_does_not_change_published_tag(self):
        ops.atomic_write(ops.tag_path("backend"), "published\n")
        with patch.object(ops, "new_tag", return_value="candidate"), patch.object(
            ops, "run", return_value=subprocess.CompletedProcess([], 0, "sha256:new\n", "")
        ):
            ops.build_image("backend", self.config)
        self.assertEqual(ops.tag_path("backend").read_text(), "published\n")
        self.assertEqual(json.loads(ops.built_path("backend").read_text())["tag"], "candidate")

    def test_failed_build_preserves_previous_candidate(self):
        previous = self.candidate()
        with patch.object(ops, "new_tag", return_value="candidate"), patch.object(
            ops, "run", side_effect=RuntimeError("build failed")
        ):
            with self.assertRaisesRegex(RuntimeError, "build failed"):
                ops.build_image("backend", self.config)
        self.assertEqual(json.loads(ops.built_path("backend").read_text()), previous)

    def test_retagged_candidate_is_not_pushed(self):
        self.candidate()
        with patch.object(ops, "run", return_value=subprocess.CompletedProcess([], 0, "sha256:other\n", "")) as execute:
            with self.assertRaisesRegex(RuntimeError, "изменился после сборки"):
                ops.push_image("backend", self.config)
        self.assertEqual(execute.call_count, 1)

    def test_unique_tags_for_repeated_builds_of_same_commit(self):
        with patch.object(ops, "run", return_value=subprocess.CompletedProcess([], 0, "abc123\n", "")):
            tags = {ops.new_tag() for _ in range(20)}
        self.assertEqual(len(tags), 20)
        for tag in tags:
            ops.valid_tag(tag)

    def create_plan(self):
        def tofu(*args, **kwargs):
            if args[0] == "plan":
                ops.PLAN.write_bytes(b"saved plan")
        with patch.object(ops, "settings", return_value=self.config), patch.object(ops, "tofu", side_effect=tofu):
            ops.plan()

    def test_stale_plan_rejected_after_component_publish(self):
        self.create_plan()
        ops.atomic_write(ops.tag_path("frontend"), "new-frontend\n")
        with patch.object(ops, "settings", return_value=self.config), patch.object(ops, "tofu") as tofu:
            with self.assertRaisesRegex(RuntimeError, "изменились"):
                ops.apply()
            tofu.assert_not_called()

    def test_stale_plan_rejected_after_tfvars_change(self):
        self.create_plan()
        (ops.INFRA / "99.auto.tfvars").write_text('ingress_host = "changed.example.com"')
        with patch.object(ops, "settings", return_value=self.config), patch.object(ops, "tofu") as tofu:
            with self.assertRaisesRegex(RuntimeError, "изменились"):
                ops.apply()
            tofu.assert_not_called()

    def test_replaced_plan_rejected(self):
        self.create_plan()
        ops.PLAN.write_bytes(b"different plan")
        with patch.object(ops, "settings", return_value=self.config), patch.object(ops, "tofu") as tofu:
            with self.assertRaisesRegex(RuntimeError, "изменились"):
                ops.apply()
            tofu.assert_not_called()

    def test_stale_plan_rejected_after_environment_variable_change(self):
        self.create_plan()
        with patch.dict(os.environ, {"TF_VAR_acme_staging": "true"}), patch.object(
            ops, "settings", return_value=self.config
        ), patch.object(ops, "tofu") as tofu:
            with self.assertRaisesRegex(RuntimeError, "изменились"):
                ops.apply()
            tofu.assert_not_called()

    def test_apply_waits_for_both_rollouts_and_removes_plan(self):
        self.create_plan()
        with patch.object(ops, "settings", return_value=self.config), patch.object(ops, "tofu") as tofu, patch.object(ops, "kube") as kube:
            ops.apply()
            tofu.assert_called_once_with("apply", "-input=false", ops.PLAN)
            self.assertEqual(kube.call_count, 2)
        self.assertFalse(ops.PLAN.exists())
        self.assertFalse(ops.PLAN_META.exists())

    def test_initial_credentials_unknown_value_is_actionable(self):
        with patch.object(ops, "tofu", return_value=subprocess.CompletedProcess([], 0, "(known after apply)\n", "")):
            with self.assertRaisesRegex(RuntimeError, "missing input value"):
                ops.console('nonsensitive(var.postgres_password != "")', inspect_only=False)

    def test_config_update_preserves_other_settings_and_is_private(self):
        ops.update_local_config({"postgres_password": "dummy", "manage_certificate": True})
        ops.update_local_config({"manage_certificate": False})
        self.assertEqual(json.loads(ops.LOCAL_CONFIG.read_text()), {"postgres_password": "dummy", "manage_certificate": False})
        self.assertEqual(ops.LOCAL_CONFIG.stat().st_mode & 0o777, 0o600)

    def http_result(self, status="200", headers="", body="<html></html>", returncode=0):
        def execute(*args, **kwargs):
            Path(args[args.index("--dump-header") + 1]).write_text(headers)
            Path(args[args.index("--output") + 1]).write_text(body)
            self.assertNotIn("--insecure", args)
            self.assertNotIn("-k", args)
            self.assertNotIn("--location", args)
            return subprocess.CompletedProcess(args, returncode, status, "TLS failure" if returncode else "")
        return execute

    def test_503_is_not_success(self):
        with patch.object(ops, "run", side_effect=self.http_result(status="503", body="Service unavailable")):
            with self.assertRaisesRegex(RuntimeError, "Ожидался HTTP 200"):
                ops.check_http("app.example.com")

    def test_tls_error_is_not_ignored(self):
        with patch.object(ops, "run", side_effect=self.http_result(status="000", returncode=60)):
            with self.assertRaisesRegex(RuntimeError, "TLS failure"):
                ops.check_http("app.example.com")

    def test_ssl_check_waits_for_ingress_to_load_ready_certificate(self):
        config = {**self.config, "manage_certificate": True}
        with patch.object(ops, "kube") as kube, patch.object(
            ops, "check_http", side_effect=[ops.TLSCertificateError("old certificate"), None]
        ) as check, patch.object(ops.time, "sleep") as sleep:
            ops.ssl_check(config)
        kube.assert_called_once()
        self.assertEqual(check.call_count, 2)
        sleep.assert_called_once_with(2)

    def test_ssl_check_does_not_hide_persistent_invalid_certificate(self):
        config = {**self.config, "manage_certificate": False}
        with patch.object(ops, "check_http", side_effect=ops.TLSCertificateError("wrong hostname")) as check, patch.object(ops.time, "sleep") as sleep:
            with self.assertRaisesRegex(ops.TLSCertificateError, "Origin продолжает"):
                ops.ssl_check(config)
        self.assertEqual(check.call_count, 10)
        self.assertEqual(sleep.call_count, 9)

    def test_ssl_check_does_not_retry_api_failures_as_certificate_errors(self):
        with patch.object(ops, "check_http", side_effect=RuntimeError("HTTP 503")), patch.object(ops.time, "sleep") as sleep:
            with self.assertRaisesRegex(RuntimeError, "HTTP 503"):
                ops.ssl_check({**self.config, "manage_certificate": False})
        sleep.assert_not_called()

    def test_proxy_must_have_cloudflare_header(self):
        with patch.object(ops, "run", side_effect=self.http_result()):
            with self.assertRaisesRegex(RuntimeError, "CF-Ray"):
                ops.check_http("app-proxy.example.com", proxy=True)
        with patch.object(ops, "run", side_effect=self.http_result(headers="CF-Ray: abc-AMS\n")):
            ops.check_http("app-proxy.example.com", proxy=True)

    def test_proxy_tls_handshake_explains_missing_cloudflare_edge_certificate(self):
        with patch.object(ops, "run", side_effect=self.http_result(status="000", returncode=35)):
            with self.assertRaisesRegex(ops.CloudflareEdgeCertificateError, "edge-сертификат"):
                ops.check_http("app-proxy.example.com", proxy=True)

    def test_health_requires_actual_api_json(self):
        with patch.object(ops, "run", side_effect=self.http_result(body="<html>proxy page</html>")):
            with self.assertRaisesRegex(RuntimeError, "не JSON"):
                ops.check_http("app.example.com", "/api/v1/health", health=True)

    def test_origin_uses_correct_host_and_ipv6_resolve(self):
        callback = self.http_result()
        with patch.dict(os.environ, {"ORIGIN_IP": "2001:db8::10"}), patch.object(ops, "run", side_effect=callback) as execute:
            ops.check_http("app.example.com", origin=True)
        self.assertIn("app.example.com:443:[2001:db8::10]", execute.call_args.args)
        self.assertEqual(execute.call_args.args[-1], "https://app.example.com/")

    def test_token_sent_via_stdin_not_process_arguments(self):
        config = {**self.config, "cloudflare_api_token_secret_name": "dns-token"}
        path = self.root / "token"
        path.write_text("test-secret-token")
        with patch.dict(os.environ, {"CF_TOKEN_FILE": str(path)}), patch.object(ops, "namespace"), patch.object(ops, "kube") as kube:
            ops.ssl_token(config)
        self.assertNotIn("test-secret-token", str(kube.call_args.args))
        self.assertEqual(json.loads(kube.call_args.kwargs["input"])["stringData"]["api-token"], "test-secret-token")


if __name__ == "__main__":
    unittest.main()
