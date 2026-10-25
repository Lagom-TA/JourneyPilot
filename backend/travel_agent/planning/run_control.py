from __future__ import annotations
from dataclasses import dataclass
from travel_agent.runtime.command_contracts import (
    RunCommand,
    RunCommandStatus,
    RunCommandType,
)
from travel_agent.runtime.run_contracts import TripRun, TripRunStatus
from travel_agent.runtime.run_lifecycle import is_cancellable
from travel_agent.runtime.run_commands import RUN_ENDED_BEFORE_CONSUMPTION
from .run_errors import RunNotCancellable, RunNotFound


@dataclass(frozen=True)
class RunControlOutcome:
    command: RunCommand
    run: TripRun
    message: str


async def refuse_cancel(run_id, trip_run_store, cause=None):
    current = await trip_run_store.get_run(run_id)
    raise RunNotCancellable(
        current.status.value if current is not None else None
    ) from cause


async def cancel_run(
    run_id: str,
    *,
    initial_run: TripRun,
    trip_run_store,
    execution_store,
    command_store,
    notify,
) -> RunControlOutcome:
    if not is_cancellable(initial_run.status):
        await refuse_cancel(run_id, trip_run_store)

    live_executor = await execution_store.has_live_lease(run_id)
    command, _created = await command_store.enqueue(
        run_id,
        RunCommandType.CANCEL,
        {"action": "cancel", "source": "control_api"},
    )
    if initial_run.status == TripRunStatus.CANCEL_REQUESTED and live_executor:
        notify(run_id)
        return RunControlOutcome(
            command=command,
            run=initial_run,
            message="取消请求已记录，正在等待工作流协作退出。",
        )
    try:
        run = await trip_run_store.request_cancel(
            run_id,
            current_node=initial_run.current_node,
            event_type="run.control_requested",
            payload={
                "action": "cancel",
                "source": "control_api",
                "command_id": command.command_id,
            },
        )
    except KeyError as exc:
        raise RunNotFound() from exc
    except RuntimeError as exc:
        await refuse_cancel(run_id, trip_run_store, exc)
        raise AssertionError("unreachable")
    notify(run_id)

    if run.status not in {TripRunStatus.CANCEL_REQUESTED, TripRunStatus.CANCELLED}:
        await command_store.settle(
            [command.command_id],
            status=RunCommandStatus.REJECTED,
            error_code=RUN_ENDED_BEFORE_CONSUMPTION,
            result={"run_status": run.status.value},
        )
        await refuse_cancel(run_id, trip_run_store)

    if run.status == TripRunStatus.CANCEL_REQUESTED and not live_executor:
        try:
            run = await trip_run_store.transition_status(
                run_id,
                TripRunStatus.CANCELLED,
                current_node=initial_run.current_node,
                event_type="run.cancelled",
                payload={
                    "reason": "no_live_executor",
                    "command_id": command.command_id,
                },
            )
        except ValueError as exc:
            await refuse_cancel(run_id, trip_run_store, exc)
            raise AssertionError("unreachable")

    if run.status == TripRunStatus.CANCELLED:
        await command_store.settle(
            [command.command_id],
            status=RunCommandStatus.CONSUMED,
            result={"run_status": run.status.value, "settled_by": "control_api"},
        )
        settled = await command_store.get(run_id, command.command_id)
        return RunControlOutcome(
            command=settled or command, run=run, message="运行已停止。"
        )
    return RunControlOutcome(
        command=command, run=run, message="取消请求已记录，正在等待工作流协作退出。"
    )
