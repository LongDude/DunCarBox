"""Evaluate the actual HCL with OpenTofu, without providers or a cluster."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


@unittest.skipUnless(shutil.which("tofu"), "OpenTofu is required for HCL evaluation")
class ImageLocalsTests(unittest.TestCase):
    def test_component_files_override_legacy_tag_independently(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            module = root / "infra/k3d-infra"
            module.mkdir(parents=True)
            source = Path(__file__).resolve().parents[2] / "k3d-infra/images.tf"
            (module / "images.tf").write_text(source.read_text())
            (module / "variables.tf").write_text('variable "image_tag" { default = "unbuilt" }\n')
            for component in ("backend", "frontend"):
                (root / component / ".tofu").mkdir(parents=True)

            def evaluate(*args):
                env = {key: value for key, value in os.environ.items()
                       if not key.startswith(("TF_VAR_", "TF_CLI_ARGS"))}
                result = subprocess.run(
                    ["tofu", f"-chdir={module}", "console", "-no-color", *args],
                    input="jsonencode({backend=local.backend_image_tag,frontend=local.frontend_image_tag})\n",
                    env=env, check=True, text=True, capture_output=True,
                )
                return json.loads(json.loads(result.stdout))

            self.assertEqual(evaluate(), {"backend": "unbuilt", "frontend": "unbuilt"})
            (module / "99.auto.tfvars").write_text('image_tag = "old-shared"\n')
            self.assertEqual(evaluate(), {"backend": "old-shared", "frontend": "old-shared"})
            (root / "frontend/.tofu/image-tag").write_text("new-frontend\n")
            self.assertEqual(evaluate(), {"backend": "old-shared", "frontend": "new-frontend"})
            (root / "backend/.tofu/image-tag").write_text("new-backend\n")
            self.assertEqual(evaluate("-var=image_tag=another-shared-tag"),
                             {"backend": "new-backend", "frontend": "new-frontend"})


if __name__ == "__main__":
    unittest.main()
