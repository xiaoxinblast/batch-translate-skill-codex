"""Focused regression tests for the CLI role runner contract."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_role


class RunRoleTest(unittest.TestCase):
    def test_cli_command_uses_supported_exec_json_contract(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            command = run_role.build_codex_command(
                ["codex", "-m", "gpt-5.6-terra"], root / "last.txt", root
            )
        self.assertIn("exec", command)
        self.assertIn("--json", command)
        self.assertIn("--skip-git-repo-check", command)
        self.assertIn("--output-last-message", command)
        self.assertNotIn("--agent", command)

    def test_windows_prefers_cmd_launcher_for_default_codex_name(self):
        with (
            mock.patch.object(run_role.os, "name", "nt"),
            mock.patch.object(
                run_role.shutil, "which", side_effect=lambda value: {
                    "codex.cmd": "C:/npm/codex.cmd",
                }.get(value),
            ),
        ):
            self.assertEqual(run_role.resolve_codex_bin("codex"), "C:/npm/codex.cmd")

    def test_run_once_completes_attempt_through_toolkit(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            input_path = root / "task.json"
            input_path.write_text("{}", encoding="utf-8")
            attempt_dir = root / "attempt"
            attempt_dir.mkdir()
            attempt = {
                "attempt_id": "attempt_001",
                "input": str(input_path),
                "input_sha256": run_role.sha256_file(input_path),
                "agent_input": str(attempt_dir / "agent_task.json"),
                "outputs": {"result": str(attempt_dir / "result.json")},
            }
            calls = []

            def fake_run_batch(toolkit, arguments, *, expect_json=False):
                del toolkit
                calls.append((arguments, expect_json))
                if arguments[0] == "agent-attempt":
                    return attempt
                if arguments[0] == "agent-complete":
                    return {"completion_event": str(attempt_dir / "completion_event.json")}
                return {}

            args = SimpleNamespace(
                stage="translator", project="project", input=None, output_name=None,
                toolkit=root, workspace=root, role_config=root / "translator.toml",
                codex_bin="codex",
            )
            with (
                mock.patch.object(run_role, "run_batch", side_effect=fake_run_batch),
                mock.patch.object(run_role, "load_role", return_value={"model": "gpt-5.6-terra"}),
                mock.patch.object(run_role, "monitor_codex", return_value=("/root/translator_001", "events.jsonl")),
            ):
                result = run_role.run_once(args, 1)

        self.assertEqual(result["agent_id"], "/root/translator_001")
        self.assertIn("--execution-surface", calls[0][0])
        self.assertEqual(calls[0][0][-1], "cli")
        self.assertEqual(calls[1][0][:2], ["agent-complete", "translator"])
        self.assertEqual(calls[2][0][:2], ["promote", "translator"])

    def test_prompt_requires_native_role_and_attempt_outputs(self):
        prompt = run_role.parent_prompt("translator", Path("translator.toml"), {
            "agent_input": "C:/attempt/agent_task.json",
            "outputs": {"result": "C:/attempt/result.json"},
        })
        self.assertIn("原生自定义角色 `translator`", prompt)
        self.assertIn("C:/attempt/result.json", prompt)
        self.assertIn("`--agent` 参数", prompt)

    def test_project_proposal_runs_without_document_attempt(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source = root / "research.json"
            source.write_text("{}", encoding="utf-8")
            output = root / "proposal.json"
            task = root / "proposal.task.json"
            task.write_text("{}", encoding="utf-8")
            calls = []

            def fake_run_batch(toolkit, arguments, *, expect_json=False):
                del toolkit
                calls.append((arguments, expect_json))
                if arguments[:2] == ["project-config", "proposal-task"]:
                    return {
                        "agent_input": str(task),
                        "output": str(output),
                        "input_sha256": run_role.sha256_file(task),
                    }
                return {}

            args = SimpleNamespace(
                stage="context-analyzer", toolkit=root, workspace=root,
                role_config=root / "context-analyzer.toml", codex_bin="codex.cmd",
                project_proposal_input=source, project_proposal_output=output,
            )
            with (
                mock.patch.object(run_role, "run_batch", side_effect=fake_run_batch),
                mock.patch.object(run_role, "load_role", return_value={"model": "gpt-5.6-luna"}),
                mock.patch.object(run_role, "monitor_codex", return_value=("/root/context_001", "events.jsonl")),
            ):
                result = run_role.run_project_proposal_once(args)

        self.assertEqual(result["agent_id"], "/root/context_001")
        self.assertEqual(calls[0][0][:2], ["project-config", "proposal-task"])
        self.assertEqual(calls[1][0], ["project-config", "validate-proposal", str(output)])

    def test_monitor_records_jsonl_completion_event(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            fake_codex = root / "fake_codex.py"
            fake_codex.write_text(
                "import json, sys\n"
                "from pathlib import Path\n"
                "args = sys.argv\n"
                "last = Path(args[args.index('--output-last-message') + 1])\n"
                "last.write_text('agent_id=/root/translator_001', encoding='utf-8')\n"
                "print(json.dumps({'type': 'thread.started', 'thread_id': 'thread_001'}), flush=True)\n",
                encoding="utf-8",
            )
            agent_id, event_log = run_role.monitor_codex(
                [sys.executable, str(fake_codex)], "work", root, root, poll_seconds=1
            )
            events = Path(event_log).read_text(encoding="utf-8")
        self.assertEqual(agent_id, "/root/translator_001")
        self.assertIn("thread_001", events)


if __name__ == "__main__":
    unittest.main()
