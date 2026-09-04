#!/usr/bin/env python3
"""
Quick validation script for skills - minimal version
"""

import ast
import json
import re
import sys
from pathlib import Path

MAX_SKILL_NAME_LENGTH = 64


def _strip_inline_comment(value: str) -> str:
    """Remove YAML comments without treating # inside quotes as a comment."""
    quote = None
    escaped = False
    for index, char in enumerate(value):
        if quote == '"' and escaped:
            escaped = False
            continue
        if quote == '"' and char == "\\":
            escaped = True
            continue
        if char in {"'", '"'}:
            if quote is None:
                quote = char
            elif quote == char:
                quote = None
        elif char == "#" and quote is None and (
            index == 0 or value[index - 1].isspace()
        ):
            return value[:index].rstrip()
    return value.strip()


def _parse_scalar(value: str):
    value = _strip_inline_comment(value)
    if not value:
        return {}
    if value in {"null", "Null", "NULL", "~"}:
        return None
    if value in {"true", "True", "TRUE"}:
        return True
    if value in {"false", "False", "FALSE"}:
        return False
    if value[:1] in {'"', "'"}:
        try:
            return ast.literal_eval(value)
        except (SyntaxError, ValueError) as exc:
            raise ValueError(f"字符串值无效: {value}") from exc
    if value[:1] in {"[", "{"}:
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            try:
                return ast.literal_eval(value)
            except (SyntaxError, ValueError) as exc:
                raise ValueError(f"流式值无效: {value}") from exc
    if re.fullmatch(r"[-+]?\d+", value):
        return int(value)
    if re.fullmatch(r"[-+]?(?:\d+\.\d*|\.\d+)(?:[eE][-+]?\d+)?", value):
        return float(value)
    return value


def _key_value(line: str):
    quote = None
    escaped = False
    for index, char in enumerate(line):
        if quote == '"' and escaped:
            escaped = False
            continue
        if quote == '"' and char == "\\":
            escaped = True
            continue
        if char in {"'", '"'}:
            if quote is None:
                quote = char
            elif quote == char:
                quote = None
        elif char == ":" and quote is None:
            key = _parse_scalar(line[:index].strip())
            if not isinstance(key, str) or not key:
                raise ValueError(f"映射键无效: {line}")
            return key, line[index + 1 :].strip()
    raise ValueError(f"缺少冒号: {line}")


def _parse_frontmatter(text: str):
    """Parse the small YAML subset used by skill frontmatter without PyYAML."""
    lines = []
    for line_number, raw in enumerate(text.splitlines(), 1):
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise ValueError(f"第 {line_number} 行使用了制表符缩进")
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        lines.append((indent, stripped, line_number))
    if not lines:
        return {}

    def parse_block(position: int, indent: int):
        if position >= len(lines) or lines[position][0] < indent:
            return {}, position
        if lines[position][0] != indent:
            raise ValueError(f"第 {lines[position][2]} 行缩进不连续")
        is_list = lines[position][1].startswith("-")
        result = [] if is_list else {}
        while position < len(lines):
            current_indent, content, line_number = lines[position]
            if current_indent < indent:
                break
            if current_indent > indent:
                raise ValueError(f"第 {line_number} 行缩进不连续")
            if content.startswith("-") != is_list:
                raise ValueError(f"第 {line_number} 行混用了映射和列表")
            if is_list:
                item_text = content[1:].strip()
                if not item_text:
                    if position + 1 < len(lines) and lines[position + 1][0] > indent:
                        item, position = parse_block(position + 1, lines[position + 1][0])
                    else:
                        item, position = None, position + 1
                else:
                    item = _parse_scalar(item_text)
                    position += 1
                result.append(item)
                continue
            key, value_text = _key_value(content)
            position += 1
            if value_text:
                result[key] = _parse_scalar(value_text)
            elif position < len(lines) and lines[position][0] > indent:
                result[key], position = parse_block(position, lines[position][0])
            else:
                result[key] = {}
        return result, position

    parsed, position = parse_block(0, lines[0][0])
    if position != len(lines) or not isinstance(parsed, dict):
        raise ValueError("顶层 frontmatter 必须是映射")
    return parsed


def validate_skill(skill_path):
    """Basic validation of a skill"""
    skill_path = Path(skill_path)

    skill_md = skill_path / "SKILL.md"
    if not skill_md.exists():
        return False, "SKILL.md not found"

    content = skill_md.read_text(encoding="utf-8")
    if not content.startswith("---"):
        return False, "No YAML frontmatter found"

    match = re.match(r"^---\r?\n(.*?)\r?\n---(?:\r?\n|$)", content, re.DOTALL)
    if not match:
        return False, "Invalid frontmatter format"

    frontmatter_text = match.group(1)

    try:
        frontmatter = _parse_frontmatter(frontmatter_text)
        if not isinstance(frontmatter, dict):
            return False, "Frontmatter must be a YAML dictionary"
    except ValueError as e:
        return False, f"Invalid YAML in frontmatter: {e}"

    allowed_properties = {"name", "description", "license", "allowed-tools", "metadata"}

    unexpected_keys = set(frontmatter.keys()) - allowed_properties
    if unexpected_keys:
        allowed = ", ".join(sorted(allowed_properties))
        unexpected = ", ".join(sorted(unexpected_keys))
        return (
            False,
            f"Unexpected key(s) in SKILL.md frontmatter: {unexpected}. Allowed properties are: {allowed}",
        )

    if "name" not in frontmatter:
        return False, "Missing 'name' in frontmatter"
    if "description" not in frontmatter:
        return False, "Missing 'description' in frontmatter"

    name = frontmatter.get("name", "")
    if not isinstance(name, str):
        return False, f"Name must be a string, got {type(name).__name__}"
    name = name.strip()
    if name:
        if not re.match(r"^[a-z0-9-]+$", name):
            return (
                False,
                f"Name '{name}' should be hyphen-case (lowercase letters, digits, and hyphens only)",
            )
        if name.startswith("-") or name.endswith("-") or "--" in name:
            return (
                False,
                f"Name '{name}' cannot start/end with hyphen or contain consecutive hyphens",
            )
        if len(name) > MAX_SKILL_NAME_LENGTH:
            return (
                False,
                f"Name is too long ({len(name)} characters). "
                f"Maximum is {MAX_SKILL_NAME_LENGTH} characters.",
            )

    description = frontmatter.get("description", "")
    if not isinstance(description, str):
        return False, f"Description must be a string, got {type(description).__name__}"
    description = description.strip()
    if description:
        if "<" in description or ">" in description:
            return False, "Description cannot contain angle brackets (< or >)"
        if len(description) > 1024:
            return (
                False,
                f"Description is too long ({len(description)} characters). Maximum is 1024 characters.",
            )

    return True, "Skill is valid!"


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python quick_validate.py <skill_directory>")
        sys.exit(1)

    valid, message = validate_skill(sys.argv[1])
    print(message)
    sys.exit(0 if valid else 1)
