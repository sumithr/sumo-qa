from sumo_qa.knowledge import NullKnowledgeProvider


def test_null_knowledge_provider_has_no_external_items() -> None:
    context = NullKnowledgeProvider().fetch_context("delivery eligibility", scope="prepare")

    assert context.items == []
    assert context.sources == []
    assert context.confidence == "low"
    assert context.domain_ids == []
    assert context.metadata["provider"] == "null"
    assert context.metadata["status"] == "no external knowledge provider configured"
