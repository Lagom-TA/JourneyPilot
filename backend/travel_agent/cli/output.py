from __future__ import annotations

import json
from typing import Any

EXIT_OK = 0
EXIT_FAILED = 1


def _emit(payload: dict[str, Any], *, as_json: bool, lines: list[str]) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for line in lines:
            print(line)


def _plan_lines(plan: Any) -> list[str]:
    from ..storage.maintenance.migrate import Decision

    census = plan.census
    lines = [
        f"数据库          {census.postgres_version.split(' on ')[0]}",
        f"迁移版本        {plan.current_revision or '（未纳管）'}  →  head {plan.head_revision}",
        f"结构指纹        {plan.fingerprint_digest[:16]}…",
        f"业务行数        {census.total_business_rows}",
        f"核心扩展        {'、'.join(census.installed_extensions) or '（无）'}",
    ]
    missing_ext = census.missing_required_extensions
    if missing_ext:
        lines.append(f"缺核心扩展      {'、'.join(missing_ext)}")
    capabilities = ", ".join(
        f"{name}={'on' if enabled else 'off'}"
        for name, enabled in census.optional_capabilities.items()
    )
    lines.append(f"可选能力        {capabilities or '（无）'}")
    if census.unmanaged_tables:
        lines.append(f"合同外的表      {'、'.join(census.unmanaged_tables)}")

    verdict = {
        Decision.MIGRATE_EMPTY: "空库：可以直接迁移（不需要备份）",
        Decision.ADOPT_BASELINE: "结构等于 baseline：将纳管（stamp）而不重复建表",
        Decision.UP_TO_DATE: "已是最新，无需迁移",
        Decision.UPGRADE: "落后于 head：迁移前会自动备份",
        Decision.REFUSE_UNKNOWN_SCHEMA: "拒绝：结构来历不明",
        Decision.REFUSE_UNKNOWN_REVISION: "拒绝：数据库的 revision 这份代码不认识",
        Decision.REFUSE_SCHEMA_AHEAD: "拒绝：数据库比代码新",
        Decision.REFUSE_NEEDS_DESTRUCTIVE_CONSENT: "拒绝：需要显式授权破坏性迁移",
        Decision.REFUSE_UNREACHABLE: "拒绝：数据库不可达",
    }[plan.decision]
    lines.append("")
    lines.append(f"判定            {plan.decision.value} —— {verdict}")

    if plan.pending_revisions:
        lines.append(f"待执行迁移      {'、'.join(plan.pending_revisions)}")
    if plan.destructive_revisions:
        lines.append(f"其中破坏性的    {'、'.join(plan.destructive_revisions)}")
    for note in plan.notes:
        lines.append(f"说明            {note}")
    for problem in plan.problems:
        lines.append(f"问题            {problem}")
    if plan.next_action:
        lines.append(f"下一步          {plan.next_action}")
    return lines
