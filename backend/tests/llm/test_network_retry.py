"""网络故障的重试判定：流式断连可重试，普通异常不重试。"""

import httpx

from travel_agent.llm.router import OpenAICompatibleLLM


def test_incomplete_chunked_read_is_retryable():
    error = httpx.RemoteProtocolError(
        "peer closed connection without sending complete message body"
    )
    assert OpenAICompatibleLLM._retryable(error) is True


def test_ordinary_validation_error_is_not_retryable():
    assert OpenAICompatibleLLM._retryable(ValueError("bad output")) is False
