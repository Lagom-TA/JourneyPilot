import json
from datetime import datetime, timezone

import pytest

from tests.fixtures.itinerary import itinerary_draft, visit_entry
from tests.fixtures.research_catalog import make_catalog, make_visit_packet
from travel_agent.planning.delivery.public.itinerary import _public_itinerary
from travel_agent.planning.delivery.evidence_basis import EvidenceBasisView
from travel_agent.planning.delivery.report_projection import project_report
from travel_agent.planning.itinerary.materialize import materialize_trip_workspace
from travel_agent.planning.itinerary.models import CustomBlock, TimelineEntryRef
from travel_agent.planning.itinerary.parsing import parse_itinerary_composition
from travel_agent.planning.itinerary.title_writing import write_itinerary_copy
from travel_agent.planning.references import EntityType
from travel_agent.planning.requirements.inputs import UserInputAnchor
from travel_agent.planning.requirements.place_names import (
    CONTROLLED_DESTINATION_ANCHOR_PREFIX,
)
from travel_agent.planning.research.evidence import FactStoreSnapshot
from travel_agent.planning.weather.models import WeatherContextSnapshot
from travel_agent.runtime.cancellation import RunCancelled
from travel_agent.runtime.deadlines import DeadlineObservation
from travel_agent.runtime.operations import ModelWindowClosed
from travel_agent.storage.worker_journal_store import JournalConflict
from travel_agent.runtime.budget import (
    RunBudgetExhausted,
    RunBudgetSnapshot,
    RunBudgetUsage,
)


def _workspace(days=1, *, with_identity=False):
    placements = [visit_entry("10:00", "11:00")]
    payload = itinerary_draft(placements)
    if days == 2:
        payload["duration_days"] = 2
        second_visit = visit_entry("10:00", "11:00")
        second_visit["planned_start"] = "2026-10-11T10:00:00+09:00"
        second_visit["planned_end"] = "2026-10-11T11:00:00+09:00"
        payload["days"].append(
            {
                **payload["days"][0],
                "day_id": "day_2",
                "day": 2,
                "date": "2026-10-11",
                "placements": [second_visit],
            }
        )
    composition = parse_itinerary_composition(json.dumps(payload))
    packet = make_visit_packet(
        "candidate_visit",
        "旧景点",
    )
    catalog = make_catalog(packet)
    anchors = []
    if with_identity:
        destination_id = composition.days[0].destination_id
        anchors.append(
            UserInputAnchor(
                anchor_id="anchor_destination",
                field_path=f"{CONTROLLED_DESTINATION_ANCHOR_PREFIX}{destination_id}",
                value={"place_id": destination_id, "name": "东京"},
                input_kind="controlled_identity",
            )
        )
    return materialize_trip_workspace(
        run_id="run_test",
        workspace_revision=0,
        composition=composition,
        catalog=catalog,
        requirements="东京行程需求",
        composition_mutations=[],
        user_input_anchors=anchors,
    )


class _CopyModel:
    def __init__(self, *, fail=False, missing_day=False, reverse_days=False):
        self.calls = 0
        self.fail = fail
        self.missing_day = missing_day
        self.reverse_days = reverse_days

    async def ainvoke(self, messages, **kwargs):
        self.calls += 1
        if self.fail:
            raise RuntimeError("model unavailable")
        payload = json.loads(messages[-1]["content"])
        days = [
            {"day_id": day["day_id"], "theme": f"第{day['day']}天慢慢逛吃旧城街"}
            for day in payload["days"]
        ]
        if self.missing_day:
            days = days[:-1]
        if self.reverse_days:
            days.reverse()
        return json.dumps(
            {"title": "两天逛吃旧城慢慢散步", "days": days}, ensure_ascii=False
        )


@pytest.mark.asyncio
async def test_title_writing_maps_copy_by_day_id_and_keeps_facts():
    workspace = _workspace(days=2)
    before = workspace.itinerary.model_dump()
    model = _CopyModel(reverse_days=True)

    updated = await write_itinerary_copy(workspace, model)

    assert model.calls == 1
    assert updated.itinerary.title == "两天逛吃旧城慢慢散步"
    assert [day.theme for day in updated.itinerary.day_plans] == [
        "第1天慢慢逛吃旧城街",
        "第2天慢慢逛吃旧城街",
    ]
    after = updated.itinerary.model_dump()
    after["title"] = before["title"]
    for previous, current in zip(before["day_plans"], after["day_plans"]):
        current["theme"] = previous["theme"]
    assert after == before


@pytest.mark.asyncio
async def test_title_writing_failure_keeps_existing_copy_and_is_bounded():
    workspace = _workspace()
    original_title = workspace.itinerary.title
    original_themes = [day.theme for day in workspace.itinerary.day_plans]
    model = _CopyModel(fail=True)

    updated = await write_itinerary_copy(workspace, model)

    assert model.calls == 1
    assert updated.itinerary.title == original_title
    assert [day.theme for day in updated.itinerary.day_plans] == original_themes


@pytest.mark.asyncio
async def test_title_writing_budget_refusal_keeps_existing_copy_without_retry():
    workspace = _workspace()
    original_title = workspace.itinerary.title

    class _BudgetModel:
        def __init__(self):
            self.calls = 0

        async def ainvoke(self, messages, **kwargs):
            self.calls += 1
            raise RunBudgetExhausted(
                "model.ainvoke",
                "llm_calls",
                RunBudgetSnapshot(),
                RunBudgetUsage(),
            )

    model = _BudgetModel()
    updated = await write_itinerary_copy(workspace, model)

    assert model.calls == 1
    assert updated.itinerary.title == original_title


@pytest.mark.asyncio
async def test_title_writing_closed_window_keeps_copy_without_retry():
    workspace = _workspace()

    class ClosedWindowModel:
        calls = 0

        async def ainvoke(self, messages, **kwargs):
            self.calls += 1
            raise ModelWindowClosed(
                "model.ainvoke",
                DeadlineObservation(120.0, 10.0, "composition_closed"),
                "composition",
            )

    model = ClosedWindowModel()
    assert await write_itinerary_copy(workspace, model) is workspace
    assert model.calls == 1


@pytest.mark.asyncio
async def test_title_writing_propagates_cancellation_without_retry():
    workspace = _workspace()

    class CancelledModel:
        calls = 0

        async def ainvoke(self, messages, **kwargs):
            self.calls += 1
            raise RunCancelled("run_test", "itinerary_planner")

    model = CancelledModel()
    with pytest.raises(RunCancelled):
        await write_itinerary_copy(workspace, model)
    assert model.calls == 1


@pytest.mark.asyncio
async def test_title_writing_propagates_journal_conflict():
    class ConflictedModel:
        async def ainvoke(self, messages, **kwargs):
            raise JournalConflict("execution lease lost")

    with pytest.raises(JournalConflict, match="lease lost"):
        await write_itinerary_copy(_workspace(), ConflictedModel())


@pytest.mark.asyncio
async def test_missing_day_keeps_existing_copy():
    workspace = _workspace(days=2)
    model = _CopyModel(missing_day=True)

    updated = await write_itinerary_copy(workspace, model)

    assert model.calls == 1
    assert updated is workspace


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {
            "title": {"text": "对象标题"},
            "days": [{"day_id": "day_1", "theme": "第一天慢慢逛吃旧城街"}],
        },
        {
            "title": "两天逛吃旧城慢慢散步",
            "days": [{"day_id": "day_1", "theme": ["数组主题"]}],
        },
        {
            "title": "两天逛吃旧城慢慢散步",
            "days": [
                {"day_id": "day_1", "theme": "上午的行程"},
                {"day_id": "day_1", "theme": "下午的行程"},
            ],
        },
        {
            "title": "两天逛吃旧城慢慢散步",
            "days": [{"day_id": "unknown", "theme": "行程主题"}],
        },
        {
            "title": "两天逛吃旧城慢慢散步",
            "days": [{"day_id": "day_1", "theme": "   "}],
        },
        "not json",
    ],
)
async def test_invalid_copy_structure_keeps_existing_copy(payload):
    workspace = _workspace()
    original_title = workspace.itinerary.title
    original_theme = workspace.itinerary.day_plans[0].theme

    class _InvalidCopyModel:
        def __init__(self):
            self.calls = 0

        async def ainvoke(self, messages, **kwargs):
            self.calls += 1
            return payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)

    model = _InvalidCopyModel()
    updated = await write_itinerary_copy(workspace, model)

    assert model.calls == 1
    assert updated.itinerary.title == original_title
    assert updated.itinerary.day_plans[0].theme == original_theme


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("title", "theme"),
    [("标题", "短"), ("东京旅行" * 6, "第一天" * 6)],
)
async def test_copy_length_does_not_block_output(title, theme):
    workspace = _workspace()

    class CopyModel:
        calls = 0

        async def ainvoke(self, messages, **kwargs):
            self.calls += 1
            return json.dumps(
                {"title": title, "days": [{"day_id": "day_1", "theme": theme}]},
                ensure_ascii=False,
            )

    model = CopyModel()
    updated = await write_itinerary_copy(workspace, model)

    assert model.calls == 1
    assert updated.itinerary.title == title
    assert updated.itinerary.day_plans[0].theme == theme


@pytest.mark.asyncio
async def test_title_input_uses_the_ordered_itinerary_without_other_context():
    workspace = _workspace(with_identity=True)
    day = workspace.itinerary.day_plans[0]
    block = CustomBlock(item_id="rest", day_id=day.day_id, title="自由休息")
    unfinished = CustomBlock(item_id="unplaced", day_id=day.day_id, title="未安排活动")
    day = day.model_copy(
        update={
            "timeline": [
                TimelineEntryRef(
                    entry_id="rest_entry",
                    entity_type=EntityType.CUSTOM_BLOCK,
                    entity_id=block.item_id,
                ),
                *day.timeline,
            ]
        }
    )
    itinerary = workspace.itinerary.model_copy(
        update={"day_plans": [day], "custom_blocks": [block, unfinished]}
    )
    workspace = workspace.model_copy(update={"itinerary": itinerary})

    class InspectingModel:
        async def ainvoke(self, messages, **kwargs):
            assert [message["role"] for message in messages] == ["system", "user"]
            payload = json.loads(messages[1]["content"])
            assert payload.keys() == {"current_title", "destinations", "duration_days", "days"}
            assert payload["days"][0] == {
                "day_id": day.day_id,
                "day": 1,
                "date": "2026-10-10",
                "city": "东京",
                "lodging": [],
                "timeline": [
                    {"type": "custom_block", "content": "自由休息"},
                    {"type": "visit_stop", "content": "旧景点"},
                ],
            }
            return json.dumps(
                {"title": "东京之旅", "days": [{"day_id": day.day_id, "theme": "慢逛东京"}]},
                ensure_ascii=False,
            )

    updated = await write_itinerary_copy(workspace, InspectingModel())

    assert updated.itinerary.title == "东京之旅"
    assert updated.itinerary.day_plans[0].theme == "慢逛东京"


@pytest.mark.asyncio
async def test_repeated_public_projection_does_not_call_the_model_again():
    workspace = _workspace()
    model = _CopyModel()
    updated = await write_itinerary_copy(workspace, model)

    _public_itinerary(
        updated.itinerary,
        EvidenceBasisView.from_itinerary(updated.itinerary),
    )
    _public_itinerary(
        updated.itinerary,
        EvidenceBasisView.from_itinerary(updated.itinerary),
    )

    assert model.calls == 1


@pytest.mark.asyncio
async def test_report_projection_reads_the_same_formal_title():
    workspace = _workspace(with_identity=True)
    model = _CopyModel()
    updated = await write_itinerary_copy(workspace, model)
    catalog = updated.recommendation_catalog
    facts = FactStoreSnapshot(
        fact_data_revision=0,
        source_records=[
            source
            for packet in catalog.research_packets
            for source in packet.source_records
        ],
        fact_assertions=[
            fact
            for packet in catalog.research_packets
            for fact in packet.fact_assertions
        ],
        field_provenance=[
            provenance
            for packet in catalog.research_packets
            for provenance in packet.field_provenance
        ],
    )
    report = project_report(
        updated,
        facts,
        WeatherContextSnapshot(
            weather_data_revision=0,
            trip_start_date=updated.itinerary.day_plans[0].date,
            trip_end_date=updated.itinerary.day_plans[-1].date,
            days=[],
            retrieved_at=datetime.now(timezone.utc),
        ),
        generated_at=datetime.now(timezone.utc),
    )

    assert report.document.title == updated.itinerary.title
    assert report.document.days[0].theme == updated.itinerary.day_plans[0].theme
