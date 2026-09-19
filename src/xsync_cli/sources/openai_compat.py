"""The reader of an OpenAI-compatible model endpoint.

This module knows nothing about a harness. It makes Model objects.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable

from xsync_cli.core.model import Model


class SourceError(Exception):
    """The endpoint answered, but the answer is wrong."""


class EndpointUnreachable(SourceError):
    """The endpoint did not answer."""


def _as_bool(value: Any) -> bool:
    return value is True


def _as_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def parse_models(payload: dict[str, Any]) -> list[Model]:
    """Make Model objects from a `/models` payload.

    The function accepts an endpoint that reports no capabilities. The
    absent fields then hold None or False.
    """
    data = payload.get("data")
    if not isinstance(data, list):
        raise SourceError("the answer has no `data` list. Check the base URL.")

    models: list[Model] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        slug = entry.get("id")
        if not isinstance(slug, str) or not slug:
            continue
        capabilities = entry.get("capabilities")
        if not isinstance(capabilities, dict):
            capabilities = {}
        reported_capabilities = frozenset(
            name
            for name in ("vision", "reasoning", "tools", "search")
            if isinstance(capabilities.get(name), bool)
        )
        context_window = _as_int(capabilities.get("contextWindow")) or _as_int(
            entry.get("context_length")
        )
        max_output = _as_int(capabilities.get("maxOutput")) or _as_int(
            entry.get("max_completion_tokens")
        )
        models.append(
            Model(
                slug=slug,
                context_window=context_window,
                max_output=max_output,
                vision=_as_bool(capabilities.get("vision")),
                reasoning=_as_bool(capabilities.get("reasoning")),
                tools=_as_bool(capabilities.get("tools")),
                search=_as_bool(capabilities.get("search")),
                owned_by=entry.get("owned_by"),
                reported_capabilities=reported_capabilities,
            )
        )
    models.sort(key=lambda model: model.slug)
    return models


def fetch_models(
    base_url: str,
    api_key: str | None,
    timeout: float = 10.0,
    retries: int = 2,
    opener: Callable[..., Any] | None = None,
) -> list[Model]:
    """Read `{base_url}/models` and make Model objects.

    The function tries the request `retries + 1` times. The `opener`
    argument exists for the tests.
    """
    url = f"{base_url.rstrip('/')}/models"
    headers = {"Accept": "application/json", "User-Agent": "xsync-cli"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, headers=headers)
    open_url = opener or urllib.request.urlopen

    last: Exception | None = None
    for _ in range(retries + 1):
        try:
            with open_url(request, timeout=timeout) as response:
                raw = response.read()
            break
        except urllib.error.HTTPError as error:
            if error.code in (401, 403):
                raise SourceError(
                    f"the endpoint refused the request with status {error.code}. "
                    "Check the API key."
                ) from None
            last = error
        except OSError as error:
            last = error
    else:
        raise EndpointUnreachable(f"no answer from {url}: {last}") from None

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise SourceError(f"the answer is not JSON: {error}") from None
    if not isinstance(payload, dict):
        raise SourceError("the answer is not a JSON object.")
    return parse_models(payload)
