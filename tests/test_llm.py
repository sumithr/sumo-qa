import asyncio

from sumo_qa.llm import AsyncMockLLMClient, MockLLMClient, VertexAIClient


def test_mock_llm_is_deterministic() -> None:
    client = MockLLMClient()

    first = client.complete("system", "What should QA test?")
    second = client.complete("system", "What should QA test?")

    assert first == second
    assert first.metadata["external_calls"] == "false"


def test_mock_llm_returns_empty_content_to_signal_no_llm() -> None:
    client = MockLLMClient()

    response = client.complete("system", "anything")

    assert response.content == ""
    assert "No external LLM is configured" in response.metadata["note"]


def test_async_mock_llm_returns_same_honest_empty_payload() -> None:
    client = AsyncMockLLMClient()

    response = asyncio.run(client.complete("system", "anything"))

    assert response.content == ""
    assert response.metadata["external_calls"] == "false"
    assert "No external LLM is configured" in response.metadata["note"]


def test_host_sampling_client_invokes_host_session_create_message() -> None:
    from sumo_qa.llm import HostSamplingClient

    captured: dict = {}

    class _FakeSession:
        async def create_message(self, messages, **kwargs):
            captured["messages"] = messages
            captured["kwargs"] = kwargs

            class _Result:
                model = "claude-opus-via-host"

                class content:
                    type = "text"
                    text = "host LLM produced this narrative"

            return _Result()

    client = HostSamplingClient(session=_FakeSession(), max_tokens=512)
    response = asyncio.run(client.complete("system prompt body", "user prompt body"))

    assert response.content == "host LLM produced this narrative"
    assert response.model == "claude-opus-via-host"
    assert response.metadata["external_calls"] == "true"
    # Confirm we sent the user prompt as the user message and system_prompt separately
    assert captured["kwargs"]["system_prompt"] == "system prompt body"
    assert captured["kwargs"]["max_tokens"] == 512
    assert any("user prompt body" in str(getattr(m, "content", m)) for m in captured["messages"])


def test_vertex_client_is_phase_1_stub() -> None:
    client = VertexAIClient(project="demo")

    try:
        client.complete("system", "prompt")
    except NotImplementedError as exc:
        assert "Phase 1 stub" in str(exc)
    else:
        raise AssertionError("VertexAIClient should not make calls in Phase 1")
