#!/usr/bin/env python3
"""Validate toolkit provenance and workflow protocol compatibility."""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from pathlib import Path


EXPECTED_REPOSITORY = "github.com/xiaoxinblast/batch-translate"
REQUIRED_PROTOCOL = 10
SUPPORTED_TOOLKIT_MAJOR = 10


def canonical_repository(remote: str) -> str:
    value = remote.strip().lower().replace("\\", "/")
    if value.startswith("git@"):
        value = value.replace(":", "/", 1)
    for prefix in ("https://", "http://", "ssh://", "git://"):
        if value.startswith(prefix):
            value = value[len(prefix):]
            break
    if value.startswith("git@"):
        value = value[4:]
    return value.removesuffix(".git").rstrip("/")


def read_origin(toolkit: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(toolkit), "remote", "get-url", "origin"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def read_version(toolkit: Path) -> dict:
    result = subprocess.run(
        [sys.executable, str(toolkit / "batch.py"), "version", "--json"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(result.stdout)


def parse_version_contract(source: str) -> dict:
    values = {}
    tree = ast.parse(source)
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id in {
            "TOOLKIT_VERSION", "WORKFLOW_PROTOCOL_VERSION"
        }:
            values[target.id] = ast.literal_eval(node.value)
    return {
        "toolkit_version": values.get("TOOLKIT_VERSION"),
        "workflow_protocol": values.get("WORKFLOW_PROTOCOL_VERSION"),
    }


def read_revision_version(toolkit: Path, revision: str) -> dict:
    result = subprocess.run(
        ["git", "-C", str(toolkit), "show", f"{revision}:toolkit_version.py"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return parse_version_contract(result.stdout)


def validate_version(version: dict) -> None:
    protocol = version.get("workflow_protocol")
    if protocol != REQUIRED_PROTOCOL:
        raise RuntimeError(
            f"工作流协议不兼容: 工具包={protocol!r}, skill={REQUIRED_PROTOCOL}"
        )
    version_text = str(version.get("toolkit_version") or "")
    match = re.fullmatch(r"(\d+)\.\d+\.\d+", version_text)
    if not match or int(match.group(1)) != SUPPORTED_TOOLKIT_MAJOR:
        raise RuntimeError(
            f"工具包版本不兼容: {version_text!r}; skill 仅支持 "
            f"{SUPPORTED_TOOLKIT_MAJOR}.x"
        )


def validate(
    toolkit: Path,
    remote_only: bool = False,
    revision: str | None = None,
) -> dict | None:
    toolkit = toolkit.resolve()
    if not (toolkit / ".git").exists():
        raise RuntimeError(f"工具包不是 Git 仓库: {toolkit}")
    remote = read_origin(toolkit)
    actual_repository = canonical_repository(remote)
    if actual_repository != EXPECTED_REPOSITORY:
        raise RuntimeError(
            f"origin 不受信任: {remote!r}; 预期 {EXPECTED_REPOSITORY}"
        )
    if remote_only:
        return None
    version = (
        read_revision_version(toolkit, revision) if revision else read_version(toolkit)
    )
    validate_version(version)
    return version


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("toolkit", type=Path)
    parser.add_argument("--remote-only", action="store_true")
    parser.add_argument(
        "--revision",
        default=None,
        help="merge 前检查指定 Git revision 的版本契约",
    )
    args = parser.parse_args()
    if args.remote_only and args.revision:
        parser.error("--remote-only 与 --revision 不能同时使用")
    try:
        version = validate(args.toolkit, args.remote_only, args.revision)
    except (OSError, RuntimeError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(f"FATAL: {exc}")
        raise SystemExit(2)
    if version is None:
        print(f"OK: origin = {EXPECTED_REPOSITORY}")
    else:
        print(
            f"OK: toolkit {version['toolkit_version']}, "
            f"workflow protocol {version['workflow_protocol']}"
        )


if __name__ == "__main__":
    main()
