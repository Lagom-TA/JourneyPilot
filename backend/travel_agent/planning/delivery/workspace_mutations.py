"""交付 Workspace 的变更与撤销。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pydantic import TypeAdapter
from travel_agent.planning.delivery.bundle import DeliveryBundle
from travel_agent.planning.delivery.workspace_projection import _mutation_bundle
from travel_agent.planning.itinerary.mutations.apply import apply_workspace_v2_mutation
from travel_agent.planning.itinerary.mutations.contracts import (
    ApplyWeatherAdjustmentMutation,
)
from travel_agent.planning.itinerary.mutations.contracts import (
    DeleteCustomBlockMutation,
)
from travel_agent.planning.itinerary.mutations.contracts import (
    DeleteLodgingStayMutation,
)
from travel_agent.planning.itinerary.mutations.contracts import (
    DeleteTransportLegMutation,
)
from travel_agent.planning.itinerary.mutations.contracts import (
    WorkspaceSnapshotInversePatch,
)
from travel_agent.planning.itinerary.mutations.contracts import WorkspaceV2InversePatch
from travel_agent.planning.itinerary.mutations.contracts import WorkspaceV2Mutation
from travel_agent.planning.itinerary.mutations.contracts import (
    WorkspaceV2MutationApplication,
)
from travel_agent.planning.itinerary.mutations.contracts import WorkspaceV2MutationError
from travel_agent.planning.itinerary.mutations.undo import apply_workspace_v2_inverse
from travel_agent.storage.delivery_bundle_store import BundleCommitKind
from travel_agent.storage.delivery_bundle_store import BundleCommitResult
from travel_agent.storage.delivery_bundle_store import BundleIdempotencyMismatch
from travel_agent.storage.delivery_bundle_store import BundleRevisionConflict
from travel_agent.storage.delivery_bundle_store import BundleRevisionVector
from travel_agent.storage.delivery_bundle_store import DeliveryBundleStore
from typing import Callable
from typing import Optional
from uuid import uuid4


Clock = Callable[[], datetime]


IdFactory = Callable[[], str]


INVERSE_ADAPTER = TypeAdapter(WorkspaceV2InversePatch)


@dataclass(frozen=True)
class WorkspaceBundleMutationResult:
    application: WorkspaceV2MutationApplication
    commit: Optional[BundleCommitResult]


@dataclass(frozen=True)
class WorkspaceMutationPreview:
    application: WorkspaceV2MutationApplication
    total_cost_delta_cny: Optional[float]
    explicit_confirmation: bool = False

    @property
    def requires_confirmation(self) -> bool:
        return self.explicit_confirmation or self.total_cost_delta_cny not in (
            None,
            0.0,
        )


class WorkspaceV2Service:
    def __init__(
        self,
        store: DeliveryBundleStore,
        *,
        clock: Clock = lambda: datetime.now(timezone.utc),
        id_factory: IdFactory = lambda: f"bundle_{uuid4().hex}",
    ) -> None:
        self._store = store
        self._clock = clock
        self._id_factory = id_factory

    async def preview(
        self,
        *,
        run_id: str,
        expected: BundleRevisionVector,
        mutation: WorkspaceV2Mutation,
    ) -> WorkspaceMutationPreview:
        """应用 reducer，但不持久化，也不移动当前 Bundle 指针。"""

        current = await self._current(run_id, expected)
        application = apply_workspace_v2_mutation(
            current.workspace,
            mutation,
            current.weather_snapshot,
        )
        before = current.workspace.itinerary.cost_summary.known_subtotal_cny
        after = application.workspace.itinerary.cost_summary.known_subtotal_cny
        delta = None if before is None or after is None else after - before
        return WorkspaceMutationPreview(
            application=application,
            total_cost_delta_cny=delta,
            explicit_confirmation=isinstance(
                mutation,
                (
                    ApplyWeatherAdjustmentMutation,
                    DeleteCustomBlockMutation,
                    DeleteLodgingStayMutation,
                    DeleteTransportLegMutation,
                ),
            ),
        )

    async def apply(
        self,
        *,
        run_id: str,
        expected: BundleRevisionVector,
        mutation: WorkspaceV2Mutation,
        idempotency_key: str,
    ) -> WorkspaceBundleMutationResult:
        """在提交时以乐观 CAS 应用 Workspace 变更。

        读取与纯计算不在同一个数据库锁内；使用相同 ``expected`` 向量的并发提交
        只有一个成功，另一个抛出 ``BundleRevisionConflict``，调用方需重新读取后
        重试。
        """
        mutation_payload = mutation.model_dump(mode="json")
        mutation_request = {
            "operation": "workspace_mutation",
            "mutation": mutation_payload,
            "base_bundle_id": expected.bundle_id,
            "base_workspace_revision": expected.workspace_revision,
            "base_fact_data_revision": expected.fact_data_revision,
            "base_weather_data_revision": expected.weather_data_revision,
        }
        replay = await self._store.get_commit(run_id, idempotency_key)
        if replay is not None:
            if replay.metadata.get("mutation_request") != mutation_request:
                raise BundleIdempotencyMismatch(
                    "idempotency key was used for another workspace mutation"
                )
            inverse = (
                INVERSE_ADAPTER.validate_python(replay.inverse_patch)
                if replay.inverse_patch is not None
                else None
            )
            return WorkspaceBundleMutationResult(
                application=WorkspaceV2MutationApplication(
                    workspace=replay.result.bundle.workspace,
                    changed=replay.metadata.get("mutation_outcome") != "no_op",
                    label=replay.metadata.get("label"),
                    inverse=inverse,
                ),
                commit=replay.result,
            )
        current = await self._current(run_id, expected)
        application = apply_workspace_v2_mutation(
            current.workspace,
            mutation,
            current.weather_snapshot,
        )
        if not application.changed:
            receipt = await self._store.record_noop_receipt(
                run_id=run_id,
                idempotency_key=idempotency_key,
                expected=expected,
                kind=BundleCommitKind.WORKSPACE_MUTATION_RECEIPT,
                idempotency_request=mutation_request,
                metadata={
                    "mutation": mutation_payload,
                    "mutation_request": mutation_request,
                    "mutation_outcome": "no_op",
                    "label": application.label,
                },
            )
            return WorkspaceBundleMutationResult(
                application=application, commit=receipt
            )
        bundle = _mutation_bundle(
            current,
            application.workspace,
            bundle_id=self._id_factory(),
            created_at=self._clock(),
        )
        commit = await self._store.commit(
            bundle=bundle,
            kind=BundleCommitKind.WORKSPACE_MUTATION,
            idempotency_key=idempotency_key,
            expected=expected,
            inverse_patch=application.inverse.model_dump(mode="json")
            if application.inverse
            else None,
            metadata={
                "mutation": mutation_payload,
                "mutation_request": mutation_request,
                "mutation_outcome": "committed",
                "label": application.label,
            },
            idempotency_request=mutation_request,
        )
        return WorkspaceBundleMutationResult(application=application, commit=commit)

    async def undo_current(
        self,
        *,
        run_id: str,
        expected: BundleRevisionVector,
        undo_of_mutation_id: str,
        idempotency_key: str,
    ) -> BundleCommitResult:
        undo_request = {
            "operation": "workspace_undo",
            "undo_of_mutation_id": undo_of_mutation_id,
            "base_bundle_id": expected.bundle_id,
            "base_workspace_revision": expected.workspace_revision,
            "base_fact_data_revision": expected.fact_data_revision,
            "base_weather_data_revision": expected.weather_data_revision,
        }
        replay = await self._store.get_commit(run_id, idempotency_key)
        if replay is not None:
            if replay.metadata.get("undo_request") != undo_request:
                raise BundleIdempotencyMismatch(
                    "idempotency key was used for another undo mutation"
                )
            return replay.result

        head = await self._store.get_undo_head(run_id)
        if head is None or head.mutation_id != undo_of_mutation_id:
            raise WorkspaceV2MutationError(
                "undo_head_changed",
                "The current workspace operation is no longer undoable",
            )
        inverse = INVERSE_ADAPTER.validate_python(head.inverse_patch)
        current = await self._current(run_id, expected)
        workspace = apply_workspace_v2_inverse(
            current.workspace,
            inverse,
            allow_data_refresh_rebase=(
                current.workspace.workspace_revision > head.workspace_revision
            ),
        )
        bundle = _mutation_bundle(
            current,
            workspace,
            bundle_id=self._id_factory(),
            created_at=self._clock(),
        )
        result = await self._store.commit(
            bundle=bundle,
            kind=BundleCommitKind.UNDO,
            idempotency_key=idempotency_key,
            expected=expected,
            inverse_patch=WorkspaceSnapshotInversePatch(
                applied_workspace_revision=workspace.workspace_revision,
                previous_workspace=current.workspace,
            ).model_dump(mode="json"),
            metadata={
                "undo_of_mutation_id": undo_of_mutation_id,
                "undo_request": undo_request,
                "undo_inverse_type": inverse.type,
                "label": head.label,
                "semantic_label": head.semantic_label,
                "undo_label": (
                    f"撤销：{head.semantic_label}"
                    if head.label.startswith("恢复：")
                    else f"恢复：{head.semantic_label}"
                ),
            },
            idempotency_request=undo_request,
        )
        return result

    async def _current(
        self, run_id: str, expected: BundleRevisionVector
    ) -> DeliveryBundle:
        current = await self._store.get_current(run_id)
        if current is None or BundleRevisionVector.from_bundle(current) != expected:
            raise BundleRevisionConflict(
                BundleRevisionVector.from_bundle(current)
                if current is not None
                else None
            )
        return current
