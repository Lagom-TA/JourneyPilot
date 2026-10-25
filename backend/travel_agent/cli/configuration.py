from __future__ import annotations

import argparse
import json
import sys

from ..paths import REPO_ROOT
from .output import EXIT_FAILED, EXIT_OK, _emit


def cmd_config_show(args: argparse.Namespace) -> int:

    from ..config import ConfigError, load_effective_config

    try:
        effective = load_effective_config()
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_FAILED

    payload = {
        "config_path": str(effective.config_path) if effective.config_path else None,
        "sources": effective.sources,
        "effective": effective.redacted(),
    }
    lines = [
        f"配置文件        {effective.config_path or '（未找到，全部使用默认值）'}",
        "",
        *effective.report_lines(),
    ]
    _emit(payload, as_json=args.json, lines=lines)
    return EXIT_OK


def cmd_config_validate(args: argparse.Namespace) -> int:

    from ..config import ConfigError, load_effective_config

    try:
        effective = load_effective_config()
    except ConfigError as exc:
        _emit(
            {"valid": False, "error": str(exc)},
            as_json=args.json,
            lines=[str(exc)],
        )
        return EXIT_FAILED
    payload = {
        "valid": True,
        "config_path": str(effective.config_path) if effective.config_path else None,
    }
    lines = [f"配置有效：{effective.config_path or '（默认值）'}"]
    _emit(payload, as_json=args.json, lines=lines)
    return EXIT_OK


def cmd_config_env(args: argparse.Namespace) -> int:

    from ..config import env_variable_reference

    reference = env_variable_reference()
    _emit(
        {"variables": reference},
        as_json=args.json,
        lines=[f"{name:56s} → {path}" for name, path in sorted(reference.items())],
    )
    return EXIT_OK


def cmd_config_docs(args: argparse.Namespace) -> int:

    from ..config.schema_export import field_reference_markdown, json_schema_text

    artifacts = {
        REPO_ROOT / "docs" / "configuration.md": field_reference_markdown(),
        REPO_ROOT / "docs" / "config.schema.json": json_schema_text(),
    }
    stale = [
        path
        for path, content in artifacts.items()
        if not path.exists() or path.read_text(encoding="utf-8") != content
    ]
    if args.check:
        payload = {"stale": [str(path.relative_to(REPO_ROOT)) for path in stale]}
        if stale:
            lines = [
                "这些生成物与当前 schema 不一致：",
                *(f"  {path.relative_to(REPO_ROOT)}" for path in stale),
                "跑 `journeypilot config docs` 重新生成并提交。",
            ]
            _emit(payload, as_json=args.json, lines=lines)
            return EXIT_FAILED
        _emit(payload, as_json=args.json, lines=["配置文档与 schema 一致"])
        return EXIT_OK

    for path, content in artifacts.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _emit(
        {"written": [str(path.relative_to(REPO_ROOT)) for path in artifacts]},
        as_json=args.json,
        lines=[f"已写入 {path.relative_to(REPO_ROOT)}" for path in artifacts],
    )
    return EXIT_OK


def cmd_configure(args: argparse.Namespace) -> int:

    from ..config import (
        available_presets,
        get_preset,
        preset_model_section,
        write_model_section,
    )

    presets = available_presets()
    if args.list or not args.provider:
        lines = ["可用 provider preset："]
        for preset in presets:
            verified = preset.last_verified_at or "未验证"
            lines.append(
                f"  {preset.id:12s} {preset.label:22s} {preset.base_url}  (last_verified {verified})"
            )
        lines.append("")
        lines.append("用法：journeypilot configure --provider <id>")
        _emit(
            {"presets": [preset.model_dump(mode="json") for preset in presets]},
            as_json=args.json,
            lines=lines,
        )
        return EXIT_OK if args.list else EXIT_FAILED

    preset = get_preset(args.provider)
    if preset is None:
        known = ", ".join(sorted(item.id for item in presets)) or "（无）"
        print(f"没有名为 {args.provider!r} 的 preset。已知：{known}", file=sys.stderr)
        return EXIT_FAILED

    section = preset_model_section(preset)
    if args.dry_run:
        _emit(
            {"provider": preset.id, "section": section},
            as_json=args.json,
            lines=[
                f"将写入 config.yaml（{preset.label}）：",
                json.dumps(section, ensure_ascii=False, indent=2),
            ],
        )
        return EXIT_OK

    try:
        path = write_model_section(section)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_FAILED
    lines = [
        f"已按 {preset.label} 写好 {path} 的模型段。",
        "",
        "接下来设置 API Key（**不写进 config.yaml**）：",
        "  export JOURNEYPILOT_PRIMARY_MODEL__API_KEY=...",
        "  export JOURNEYPILOT_FAST_MODEL__API_KEY=...",
        "",
        f"这份 preset 上次被真实调用验证的日期：{preset.last_verified_at or '未验证'}",
    ]
    if preset.notes.strip():
        lines.extend(["", preset.notes.strip()])
    _emit(
        {"provider": preset.id, "config_path": str(path)},
        as_json=args.json,
        lines=lines,
    )
    return EXIT_OK
