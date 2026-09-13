import json
from pathlib import Path

import pytest

from xsync_cli.sources.openai_compat import (
    EndpointUnreachable,
    SourceError,
    fetch_models,
    parse_models,
)

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class _Response:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_parse_reads_the_capabilities():
    models = parse_models(load("ninerouter_models.json"))
    first = models[0]
    assert first.slug == "cmc/deepseek/deepseek-v4-pro"
    assert first.context_window == 1000000
    assert first.max_output == 384000
    assert first.reasoning is True
    assert first.vision is False
    assert first.owned_by == "cmc"


def test_parse_accepts_a_payload_without_capabilities():
    models = parse_models(load("plain_openai_models.json"))
    only = models[0]
    assert only.slug == "gpt-4o-mini"
    assert only.context_window is None
    assert only.max_output is None
    assert only.reasoning is False
    assert only.tools is False


def test_parse_sorts_by_slug():
    payload = {"data": [{"id": "b"}, {"id": "a"}]}
    assert [m.slug for m in parse_models(payload)] == ["a", "b"]


def test_parse_skips_an_entry_without_an_id():
    payload = {"data": [{"id": "a"}, {"object": "model"}]}
    assert [m.slug for m in parse_models(payload)] == ["a"]


def test_parse_raises_when_data_is_absent():
    with pytest.raises(SourceError, match="data"):
        parse_models({"object": "list"})


def test_parse_falls_back_to_context_length():
    payload = {"data": [{"id": "a", "context_length": 4096}]}
    assert parse_models(payload)[0].context_window == 4096


def test_fetch_sends_the_authorization_header():
    seen = {}

    def opener(request, timeout):
        seen["url"] = request.full_url
        seen["auth"] = request.get_header("Authorization")
        return _Response(json.dumps(load("plain_openai_models.json")).encode())

    fetch_models("http://host/v1", "sk-1", opener=opener)
    assert seen["url"] == "http://host/v1/models"
    assert seen["auth"] == "Bearer sk-1"


def test_fetch_sends_no_header_without_a_key():
    seen = {}

    def opener(request, timeout):
        seen["auth"] = request.get_header("Authorization")
        return _Response(json.dumps(load("plain_openai_models.json")).encode())

    fetch_models("http://host/v1", None, opener=opener)
    assert seen["auth"] is None


def test_fetch_retries_then_raises_unreachable():
    attempts = {"count": 0}

    def opener(request, timeout):
        attempts["count"] += 1
        raise OSError("refused")

    with pytest.raises(EndpointUnreachable):
        fetch_models("http://host/v1", None, retries=2, opener=opener)
    assert attempts["count"] == 3


def test_fetch_raises_on_invalid_json():
    def opener(request, timeout):
        return _Response(b"<html>not json</html>")

    with pytest.raises(SourceError, match="JSON"):
        fetch_models("http://host/v1", None, opener=opener)
