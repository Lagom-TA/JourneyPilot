from __future__ import annotations
from dataclasses import dataclass
from travel_agent.runtime.command_contracts import (
    RunCommand,
    RunCommandStatus,
    RunCommandType,
)
from travel_agent.runtime.run_contracts import TripRunStatus
from travel_agent.planning.requirements.identity_amendments import (
    classify_locked_identity_intent,
)
from travel_agent.planning.run_errors import (
    LockedIdentitySupplement,
    RunNotAcceptingSupplement,
)

_SUPPLEMENT_IMPACT = {
    "food": ["目的地体验", "每日安排"],
    "transport": ["交通可行性", "每日路线"],
    "accommodation": ["住宿调研", "通勤范围"],
    "pace": ["每日强度", "行程编排"],
    "must_do": ["体验核验", "每日安排"],
    "other": ["相关调研任务"],
}


@dataclass(frozen=True)
class SupplementOutcome:
    command: RunCommand
    impact_scope: list[str]
    message: str


async def queue_supplement(
    run_id: str,
    *,
    run,
    category: str,
    content: str,
    trip_run_store,
    command_store,
    notify,
) -> SupplementOutcome:
    content = content.strip()
    if classify_locked_identity_intent(content).classification == "change_requested":
        raise LockedIdentitySupplement()
    if run.status != TripRunStatus.RUNNING:
        raise RunNotAcceptingSupplement()
    impact_scope = _SUPPLEMENT_IMPACT[category]
    command, created = await command_store.enqueue(
        run_id,
        RunCommandType.SUPPLEMENT,
        {
            "category": category,
            "content": content,
            "impact_scope": impact_scope,
            "source": "supplement_api",
        },
    )
    if created:
        await trip_run_store.append_event(
            run_id,
            "run.supplement_queued",
            {
                "command_id": command.command_id,
                "category": category,
                "content": content,
                "impact_scope": impact_scope,
            },
        )
    notify(run_id)
    return SupplementOutcome(
        command, impact_scope, supplement_message(command, impact_scope)
    )


def supplement_message(command: RunCommand, impact_scope: list[str]) -> str:
    """回执上那句话。命令已经有结论时，说结论，不说「即将分析」。"""

    if command.status is RunCommandStatus.CONSUMED:
        return "这条追加要求已经生效。"
    if command.status is RunCommandStatus.REJECTED:
        return "这次运行已经越过可以追加要求的阶段，这条要求不会生效。"
    return (
        f"已加入当前运行，将在下一个执行边界分析对 {'、'.join(impact_scope)} 的影响。"
    )
