"""Regression tests for the skill's installation and toolkit checks."""

from __future__ import annotations

import importlib.util
import subprocess
import tempfile
try:
    import tomllib
except ImportError:  # Python 3.10 CI
    import tomli as tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "batch-translate"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


check_toolkit = _load("check_toolkit", SKILL / "scripts" / "check_toolkit.py")
install_roles = _load("install_roles", SKILL / "scripts" / "install_roles.py")
quick_validate = _load("quick_validate", ROOT / "scripts" / "quick_validate.py")


class ToolkitCheckTest(unittest.TestCase):
    def _toolkit(self, remote: str, protocol: int = 10) -> tuple[tempfile.TemporaryDirectory, Path]:
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(root), "remote", "add", "origin", remote],
            check=True,
            capture_output=True,
        )
        (root / "batch.py").write_text(
            "import json, sys\n"
            f"print(json.dumps({{'toolkit_version': '10.0.0', 'workflow_protocol': {protocol}}}))\n",
            encoding="utf-8",
        )
        (root / "toolkit_version.py").write_text(
            "TOOLKIT_VERSION = '10.0.0'\n"
            f"WORKFLOW_PROTOCOL_VERSION = {protocol}\n",
            encoding="utf-8",
        )
        subprocess.run(
            ["git", "-C", str(root), "add", "batch.py", "toolkit_version.py"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "git", "-C", str(root),
                "-c", "user.name=Test",
                "-c", "user.email=test@example.invalid",
                "commit", "-m", "fixture",
            ],
            check=True,
            capture_output=True,
        )
        return temp, root

    def test_accepts_https_and_ssh_canonical_remote(self):
        self.assertEqual(
            check_toolkit.canonical_repository(
                "git@github.com:xiaoxinblast/batch-translate.git"
            ),
            check_toolkit.EXPECTED_REPOSITORY,
        )
        self.assertEqual(
            check_toolkit.canonical_repository(
                "https://github.com/xiaoxinblast/batch-translate.git"
            ),
            check_toolkit.EXPECTED_REPOSITORY,
        )

    def test_rejects_wrong_remote_before_update(self):
        temp, toolkit = self._toolkit("https://github.com/example/fork.git")
        self.addCleanup(temp.cleanup)
        with self.assertRaisesRegex(RuntimeError, "origin"):
            check_toolkit.validate(toolkit, remote_only=True)

    def test_rejects_incompatible_protocol(self):
        temp, toolkit = self._toolkit(
            "https://github.com/xiaoxinblast/batch-translate.git",
            protocol=6,
        )
        self.addCleanup(temp.cleanup)
        with self.assertRaisesRegex(RuntimeError, "协议不兼容"):
            check_toolkit.validate(toolkit)

    def test_rejects_unsupported_toolkit_major(self):
        with self.assertRaisesRegex(RuntimeError, "版本不兼容"):
            check_toolkit.validate_version({
                "toolkit_version": "7.0.0",
                "workflow_protocol": 10,
            })

    def test_checks_fetched_revision_without_executing_it(self):
        temp, toolkit = self._toolkit(
            "https://github.com/xiaoxinblast/batch-translate.git"
        )
        self.addCleanup(temp.cleanup)

        version = check_toolkit.validate(toolkit, revision="HEAD")

        self.assertEqual(version["workflow_protocol"], 10)


class RoleInstallTest(unittest.TestCase):
    def test_assets_match_repository_roles(self):
        for name in install_roles.MANAGED_ROLES:
            self.assertEqual(
                (ROOT / "agents" / name).read_bytes(),
                (SKILL / "assets" / "agents" / name).read_bytes(),
            )
            with open(ROOT / "agents" / name, "rb") as role_file:
                tomllib.load(role_file)

    def test_role_model_assignments_are_explicit(self):
        expected = {
            "context-analyzer.toml": ("gpt-5.6-luna", "max"),
            "translator.toml": ("gpt-5.6-terra", "max"),
            "trans-reviewer.toml": ("gpt-5.6-terra", "max"),
            "qa-reviewer.toml": ("gpt-5.6-luna", "max"),
        }
        for name, (model, effort) in expected.items():
            with open(ROOT / "agents" / name, "rb") as role_file:
                config = tomllib.load(role_file)
            self.assertEqual(config["model"], model, name)
            self.assertEqual(config["model_reasoning_effort"], effort, name)

    def test_install_preserves_unrelated_roles(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp)
            unrelated = destination / "custom-role.toml"
            unrelated.write_text("name = 'custom'\n", encoding="utf-8")

            changed = install_roles.install(destination)

            self.assertEqual(set(changed), set(install_roles.MANAGED_ROLES))
            self.assertEqual(unrelated.read_text(encoding="utf-8"), "name = 'custom'\n")
            self.assertEqual(install_roles.install(destination, check=True), [])


class QuickValidationTest(unittest.TestCase):
    def test_current_skill_validates_without_optional_yaml_dependency(self):
        valid, message = quick_validate.validate_skill(SKILL)

        self.assertTrue(valid, message)

    def test_parses_supported_nested_frontmatter(self):
        with tempfile.TemporaryDirectory() as temp:
            skill = Path(temp)
            (skill / "SKILL.md").write_text(
                "---\r\n"
                "name: sample-skill\r\n"
                "description: \"A description with # in a string\"\r\n"
                "allowed-tools: [\"read\", \"write\"]\r\n"
                "metadata:\r\n"
                "  short-description: 简短说明\r\n"
                "---\r\n\r\n正文\r\n",
                encoding="utf-8",
                newline="",
            )

            valid, message = quick_validate.validate_skill(skill)

        self.assertTrue(valid, message)

    def test_rejects_malformed_frontmatter_without_yaml_import(self):
        with tempfile.TemporaryDirectory() as temp:
            skill = Path(temp)
            (skill / "SKILL.md").write_text(
                "---\nname sample-skill\n---\n",
                encoding="utf-8",
            )

            valid, message = quick_validate.validate_skill(skill)

        self.assertFalse(valid)
        self.assertIn("Invalid YAML in frontmatter", message)


if __name__ == "__main__":
    unittest.main()
