"""Shared, cached JSON GETs for upstream weather services.

The host is a free, stateless web service, so upstream responses are kept in the
process-local cache only. Errors are never cached.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

import requests
from django.core.cache import cache

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping


def _cache_key(url: str, params: Mapping[str, Any] | None) -> str:
    raw = json.dumps([url, sorted((params or {}).items())], default=str)
    return "upstream:" + hashlib.sha256(raw.encode()).hexdigest()


def get_json(
    url: str,
    *,
    params: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: float = 10,
    ttl: int = 0,
    cacheable: Callable[[Any], bool] | None = None,
) -> Any:
    """GET ``url`` and return its JSON, caching successes for ``ttl`` seconds.

    Raises ``requests`` exceptions (including ``HTTPError``) and ``ValueError`` for
    invalid JSON, exactly as a plain ``requests.get`` would. ``cacheable`` can veto
    caching of a payload (for example one that reports an error with HTTP 200).
    """
    key = _cache_key(url, params) if ttl else ""
    if ttl:
        cached = cache.get(key)
        if cached is not None:
            return cached
    response = requests.get(url, params=params, headers=headers, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    if ttl and (cacheable is None or cacheable(data)):
        cache.set(key, data, ttl)
    return data
