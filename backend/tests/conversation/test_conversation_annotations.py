from travel_agent.conversation import information_annotations
from travel_agent.conversation.answer_presentation import OutputGuard


def test_annotation_failure_keeps_answer_and_grounded_citations(monkeypatch):
    def unavailable_annotations(text):
        raise RuntimeError("annotation renderer unavailable")

    monkeypatch.setattr(
        information_annotations, "_annotate_information_blocks", unavailable_annotations
    )
    result = OutputGuard().check(
        "营业时间为 09:00–17:00。[[fact:1]]",
        verified_claims={
            "claim_hours": {
                "claim_text": "营业时间为 09:00–17:00。",
                "evidence_ids": ["source_hours"],
            }
        },
        evidence_records=[
            {
                "evidence_id": "source_hours",
                "title": "Museum opening hours",
                "url": "https://example.com/hours",
            }
        ],
    )

    assert result.processed_output == "营业时间为 09:00–17:00。[[cite:cite_1]]"
    assert result.annotations == []
    assert len(result.citations) == 1
    assert result.citations[0]["claim_id"] == "claim_hours"
    assert result.final_grounding["contract_errors"] == []


def test_cited_block_does_not_receive_an_information_annotation():
    text = "营业时间为 09:00–17:00。[[cite:cite_1]]"

    assert information_annotations._best_effort_information_annotations(text) == (
        text,
        [],
    )


def test_information_annotations_remain_sparse_without_rewriting_text():
    text = "营业时间按现场公示。\n\n票价按现场公示。\n\n春季花期因天气而异。"

    rendered, annotations = (
        information_annotations._best_effort_information_annotations(text)
    )

    assert [item["kind"] for item in annotations] == [
        "time_sensitive",
        "seasonal_reference",
    ]
    assert rendered == (
        "营业时间按现场公示。 [[annotation:annotation_1]]\n\n"
        "票价按现场公示。\n\n"
        "春季花期因天气而异。 [[annotation:annotation_2]]"
    )
