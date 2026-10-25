"""In-memory command store shared by isolated behavior tests."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from travel_agent.runtime.command_contracts import (
    RunCommand,
    RunCommandStatus,
    RunCommandType,
    generate_run_command_id,
    run_command_digest,
)


class FakeCommandStore:
    """内存版命令表。语义与 SQL 那份一致：只有未收口的命令能被取走或改写。"""

    def __init__(self) -> None:
        self.commands: Dict[str, RunCommand] = {}

    async def enqueue(
        self,
        run_id: str,
        command_type: str | RunCommandType,
        payload: Optional[Dict[str, Any]] = None,
    ) -> tuple[RunCommand, bool]:
        body = dict(payload or {})
        digest = run_command_digest(command_type, body)
        for command in self.commands.values():
            if command.run_id == run_id and command.request_digest == digest:
                return command, False
        command = RunCommand(
            command_id=generate_run_command_id(),
            run_id=run_id,
            command_type=command_type,
            payload=body,
            request_digest=digest,
        )
        self.commands[command.command_id] = command
        return command, True

    async def claim_pending(self, run_id: str, *, limit: int = 20) -> List[RunCommand]:
        claimed = []
        for command in list(self.commands.values()):
            if (
                command.run_id != run_id
                or command.status is not RunCommandStatus.PENDING
            ):
                continue
            command.status = RunCommandStatus.CLAIMED
            claimed.append(command)
        return claimed[:limit]

    async def settle(
        self,
        command_ids: Sequence[str],
        *,
        status: RunCommandStatus,
        result: Optional[Dict[str, Any]] = None,
        error_code: Optional[str] = None,
    ) -> int:
        settled = 0
        for command_id in command_ids:
            command = self.commands.get(command_id)
            if command is None or not command.is_open:
                continue
            command.status = status
            command.result = result
            command.error_code = error_code
            settled += 1
        return settled

    async def settle_open_for_run(
        self,
        run_id: str,
        *,
        status: RunCommandStatus,
        command_types=None,
        result: Optional[Dict[str, Any]] = None,
        error_code: Optional[str] = None,
    ) -> List[RunCommand]:
        kinds = (
            {
                RunCommandType(str(getattr(value, "value", value)))
                for value in command_types
            }
            if command_types is not None
            else set(RunCommandType)
        )
        settled = []
        for command in self.commands.values():
            if command.run_id != run_id or not command.is_open:
                continue
            if command.command_type not in kinds:
                continue
            command.status = status
            command.result = result
            command.error_code = error_code
            settled.append(command)
        return settled
