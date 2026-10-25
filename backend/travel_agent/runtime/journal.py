from __future__ import annotations

import contextvars
import hashlib
import json


current_worker_journal = contextvars.ContextVar("worker_journal", default=None)


current_execution_lease = contextvars.ContextVar("execution_lease", default=None)


class WorkerJournal:
    def __init__(self, store, run_id, scope_id, version, payload, lease_token):
        self.store, self.run_id, self.scope_id = store, run_id, scope_id
        self.version, self.payload, self.lease_token = version, payload, lease_token
        self.tool_cursor = 0

    async def commit(self):
        self.version = await self.store.save(
            self.run_id,
            self.scope_id,
            self.version,
            self.payload,
            lease_token=self.lease_token,
        )

    def next_tool(self, name, args):
        cursor = self.tool_cursor
        self.tool_cursor += 1
        identity = json.dumps([name, args], sort_keys=True, ensure_ascii=False)
        return f"{cursor}:{hashlib.sha256(identity.encode()).hexdigest()}"
