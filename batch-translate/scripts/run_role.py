#!/usr/bin/env python3
"""Run one batch-translate role through the supported Codex CLI contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import tomllib
from pathlib import Path
from typing import Any


STAGES = {"context-analyzer", "translator", "trans-reviewer", "qa-reviewer"}
MAX_RETRIES = 1
IDLE_TIMEOUT_SECONDS = 10 * 60
TOTAL_TIMEOUT_SECONDS = 45 * 60
POLL_SECONDS = 30
_AGENT_ID_RE = re.compile(r"(?:agent_id|agent-id)\s*[:=]\s*([^\s`]+)", re.I)


class RoleRunError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_role(path: Path, stage: str) -> dict[str, str]:
    try:
        value = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise RoleRunError(f"无法读取角色配置 {path}: {exc}") from exc
    required = ("name", "model", "model_reasoning_effort")
    if any(not isinstance(value.get(key), str) or not value[key].strip() for key in required):
        raise RoleRunError(f"角色配置缺少必要字段: {path}")
    if value["name"] != stage:
        raise RoleRunError(f"角色配置名称不匹配: 期望 {stage}，实际 {value['name']}")
    return {key: value[key] for key in required}


def run_batch(
    toolkit: Path, arguments: list[str], *, expect_json: bool = False,
) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, str(toolkit / "batch.py"), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RoleRunError(f"batch.py {' '.join(arguments[:2])} 失败: {detail}")
    if not expect_json:
        return {}
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RoleRunError(f"batch.py {' '.join(arguments[:2])} 未返回 JSON: {completed.stdout!r}") from exc


def parent_prompt(stage: str, role_path: Path, attempt: dict[str, Any]) -> str:
    outputs = json.dumps(attempt["outputs"], ensure_ascii=False)
    return f"""你是批量翻译的父级编排 Agent，不得亲自完成翻译或 QA。

必须使用已安装的原生自定义角色 `{stage}`，其角色配置为 `{role_path.resolve()}`。使用该角色启动一个子代理，并等待真实完成事件；不要假定 CLI 存在 `--agent` 参数。

子代理输入：`{attempt['agent_input']}`
子代理暂存输出：`{outputs}`

输入任务包含 `agent_attempt.outputs`。子代理只能写这些暂存路径，绝不能写正式批次 JSON、正式 QA 输出或工作副本。子代理完成后先确认全部暂存输出存在且非空。

最终只回复 `agent_id=<真实子代理 ID>`。如果子代理失败、超时、没有写入完整输出，明确报告失败，不能伪造 agent id 或 completion event。"""


def _extract_thread_id(event: dict[str, Any]) -> str | None:
    for key in ("thread_id", "session_id", "conversation_id"):
        value = event.get(key)
        if isinstance(value, str) and value:
            return value
    thread = event.get("thread")
    if isinstance(thread, dict) and isinstance(thread.get("id"), str):
        return thread["id"]
    return None


def _collect_events(stream: Any, event_path: Path, values: queue.Queue[str]) -> None:
    with event_path.open("w", encoding="utf-8", newline="\n") as handle:
        for line in iter(stream.readline, ""):
            handle.write(line)
            handle.flush()
            values.put(line)
    stream.close()


def terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def build_codex_command(
    command: list[str], last_message: Path, workspace: Path,
) -> list[str]:
    return [
        *command,
        "exec",
        "--json",
        "--output-last-message",
        str(last_message),
        "-C",
        str(workspace.resolve()),
        "-",
    ]


def monitor_codex(
    command: list[str],
    prompt: str,
    workspace: Path,
    attempt_dir: Path,
    *,
    idle_timeout: int = IDLE_TIMEOUT_SECONDS,
    total_timeout: int = TOTAL_TIMEOUT_SECONDS,
    poll_seconds: int = POLL_SECONDS,
) -> tuple[str, str | None]:
    event_path = attempt_dir / "codex-events.jsonl"
    last_message = attempt_dir / "codex-last-message.txt"
    full_command = build_codex_command(command, last_message, workspace)
    process = subprocess.Popen(
        full_command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert process.stdin is not None and process.stdout is not None
    process.stdin.write(prompt)
    process.stdin.close()
    values: queue.Queue[str] = queue.Queue()
    reader = threading.Thread(
        target=_collect_events, args=(process.stdout, event_path, values), daemon=True
    )
    reader.start()
    started = time.monotonic()
    last_activity = started
    thread_id: str | None = None
    timed_out: str | None = None
    while process.poll() is None:
        now = time.monotonic()
        if now - started >= total_timeout:
            timed_out = f"超过总时限 {total_timeout} 秒"
            terminate_process_tree(process)
            break
        if now - last_activity >= idle_timeout:
            timed_out = f"连续 {idle_timeout} 秒无活动"
            terminate_process_tree(process)
            break
        try:
            line = values.get(timeout=min(poll_seconds, total_timeout - (now - started)))
        except queue.Empty:
            continue
        if line.strip():
            last_activity = time.monotonic()
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        thread_id = _extract_thread_id(event) or thread_id
    process.wait()
    reader.join(timeout=5)
    while not values.empty():
        line = values.get_nowait()
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        thread_id = _extract_thread_id(event) or thread_id
    if timed_out:
        raise RoleRunError(timed_out)
    if process.returncode:
        raise RoleRunError(f"codex exec 退出码为 {process.returncode}")
    if not last_message.is_file() or not last_message.read_text(encoding="utf-8").strip():
        raise RoleRunError("codex exec 未产出最终完成消息")
    message = last_message.read_text(encoding="utf-8")
    match = _AGENT_ID_RE.search(message)
    agent_id = match.group(1) if match else (f"codex-exec/{thread_id}" if thread_id else None)
    if not agent_id:
        raise RoleRunError("完成消息和 JSONL 事件均未提供可核验的 agent id")
    return agent_id, str(event_path.resolve())


def run_once(args: argparse.Namespace, attempt_number: int) -> dict[str, Any]:
    attempt_id = f"cli_{args.stage.replace('-', '_')}_{attempt_number}_{int(time.time())}"
    batch_args = [
        "agent-attempt", args.stage, "--project", args.project,
        "--attempt-id", attempt_id, "--execution-surface", "cli",
    ]
    if args.stage == "context-analyzer":
        if args.input is None:
            raise RoleRunError("context-analyzer 需要 --input")
        if not args.output_name:
            raise RoleRunError("context-analyzer 需要 --output-name")
        batch_args.extend(["--input", str(args.input.resolve())])
        batch_args.extend(["--output-name", args.output_name])
    elif args.input is not None:
        raise RoleRunError(f"{args.stage} 的输入由当前批次自动确定，不能传 --input")
    elif args.output_name is not None:
        raise RoleRunError(f"{args.stage} 不支持 --output-name")
    attempt = run_batch(args.toolkit, batch_args, expect_json=True)
    canonical_input = Path(attempt["input"])
    if sha256_file(canonical_input) != attempt["input_sha256"]:
        raise RoleRunError("启动前任务输入已变化")
    role = load_role(args.role_config, args.stage)
    command = [args.codex_bin, "-m", role["model"]]
    agent_id, event_log = monitor_codex(
        command,
        parent_prompt(args.stage, args.role_config, attempt),
        args.workspace,
        Path(attempt["outputs"]["result"]).parent,
    )
    attempt_dir = Path(attempt["outputs"]["result"]).parent
    completion = run_batch(args.toolkit, [
        "agent-complete", args.stage,
        "--attempt-dir", str(attempt_dir),
        "--agent-id", agent_id,
        "--project", args.project,
    ], expect_json=True)
    event_value = completion.get("completion_event")
    if not isinstance(event_value, str) or not event_value:
        raise RoleRunError("batch.py agent-complete 未返回 completion_event")
    event = Path(event_value)
    if event.resolve() != (attempt_dir / "completion_event.json").resolve():
        raise RoleRunError("batch.py agent-complete 返回了 attempt 目录外的完成事件")
    run_batch(args.toolkit, [
        "promote", args.stage,
        "--attempt-dir", str(attempt_dir),
        "--agent-id", agent_id,
        "--role-config", str(args.role_config.resolve()),
        "--completion-event", str(event),
        "--project", args.project,
    ])
    return {"attempt": attempt, "agent_id": agent_id, "event_log": event_log}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="以真实 codex exec JSONL 事件运行并晋升一个 batch-translate 角色"
    )
    parser.add_argument("stage", choices=sorted(STAGES))
    parser.add_argument("--toolkit", type=Path, required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--input", type=Path, default=None)
    parser.add_argument("--output-name", default=None)
    parser.add_argument("--role-config", type=Path, default=None)
    parser.add_argument("--codex-bin", default="codex")
    args = parser.parse_args()
    args.toolkit = args.toolkit.resolve()
    if not (args.toolkit / "batch.py").is_file():
        parser.error(f"无效工具包目录: {args.toolkit}")
    if not args.workspace.is_dir():
        parser.error(f"工作目录不存在: {args.workspace}")
    if args.role_config is None:
        codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        args.role_config = codex_home / "agents" / f"{args.stage}.toml"
    if not args.role_config.is_file():
        parser.error(f"角色配置不存在: {args.role_config}")
    errors: list[str] = []
    for attempt_number in range(1, MAX_RETRIES + 2):
        try:
            result = run_once(args, attempt_number)
            print(json.dumps({
                "status": "promoted",
                "stage": args.stage,
                "agent_id": result["agent_id"],
                "attempt_id": result["attempt"]["attempt_id"],
                "event_log": result["event_log"],
            }, ensure_ascii=False))
            return
        except RoleRunError as exc:
            errors.append(str(exc))
    print("FATAL: 角色运行失败（固定输入仅重试一次）: " + " | ".join(errors), file=sys.stderr)
    raise SystemExit(1)


if __name__ == "__main__":
    main()
