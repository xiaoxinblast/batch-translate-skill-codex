#!/usr/bin/env python3
"""Install the skill-bundled Codex roles without touching unrelated roles."""

from __future__ import annotations

import argparse
import os
import shutil
import tempfile
from pathlib import Path


MANAGED_ROLES = (
    "context-analyzer.toml",
    "translator.toml",
    "trans-reviewer.toml",
    "qa-reviewer.toml",
)


def default_destination() -> Path:
    codex_home = os.environ.get("CODEX_HOME")
    return (Path(codex_home) if codex_home else Path.home() / ".codex") / "agents"


def install(destination: Path, check: bool = False) -> list[str]:
    source = Path(__file__).resolve().parent.parent / "assets" / "agents"
    missing = [name for name in MANAGED_ROLES if not (source / name).is_file()]
    if missing:
        raise FileNotFoundError(f"skill 缺少角色资源: {missing}")
    destination.mkdir(parents=True, exist_ok=True)
    changed = []
    for name in MANAGED_ROLES:
        src = source / name
        dst = destination / name
        if dst.is_file() and dst.read_bytes() == src.read_bytes():
            continue
        changed.append(name)
        if check:
            continue
        with tempfile.NamedTemporaryFile(
            prefix=f".{name}.", dir=destination, delete=False
        ) as temp_file:
            temp_path = Path(temp_file.name)
        try:
            shutil.copy2(src, temp_path)
            os.replace(temp_path, dst)
        finally:
            temp_path.unlink(missing_ok=True)
    return changed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, default=default_destination())
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        changed = install(args.destination, args.check)
    except OSError as exc:
        print(f"FATAL: {exc}")
        raise SystemExit(2)
    if args.check and changed:
        print(f"FATAL: 角色未同步: {', '.join(changed)}")
        raise SystemExit(1)
    action = "已同步" if changed else "无需更新"
    print(f"OK: {action} {len(changed)} 个受管角色；未触碰其他角色")


if __name__ == "__main__":
    main()
