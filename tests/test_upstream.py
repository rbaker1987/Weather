"""Tests for the shared cached upstream JSON helper."""

from unittest.mock import Mock, patch

import pytest
import requests

from weather import upstream


def _response(payload=None, error=None):
    response = Mock()
    response.json.return_value = payload
    response.raise_for_status.side_effect = error
    return response


def test_get_json_without_ttl_never_caches():
    with patch("requests.get", return_value=_response({"a": 1})) as get:
        assert upstream.get_json("https://x/y") == {"a": 1}
        assert upstream.get_json("https://x/y") == {"a": 1}

    assert get.call_count == 2


def test_get_json_caches_by_url_and_params():
    with patch("requests.get", return_value=_response({"a": 1})) as get:
        first = upstream.get_json("https://x/y", params={"q": 1}, ttl=60)
        second = upstream.get_json("https://x/y", params={"q": 1}, ttl=60)
        other = upstream.get_json("https://x/y", params={"q": 2}, ttl=60)

    assert first == second == other == {"a": 1}
    assert get.call_count == 2


def test_get_json_passes_headers_and_timeout():
    with patch("requests.get", return_value=_response({})) as get:
        upstream.get_json("https://x/y", headers={"H": "v"}, timeout=3)

    assert get.call_args.kwargs["headers"] == {"H": "v"}
    assert get.call_args.kwargs["timeout"] == 3


def test_get_json_does_not_cache_errors_or_vetoed_payloads():
    failing = _response(error=requests.HTTPError("boom"))
    with patch("requests.get", return_value=failing) as get:
        for _ in range(2):
            with pytest.raises(requests.HTTPError):
                upstream.get_json("https://x/err", ttl=60)
    assert get.call_count == 2

    with patch("requests.get", return_value=_response({"error": True})) as get:
        for _ in range(2):
            upstream.get_json(
                "https://x/veto", ttl=60, cacheable=lambda data: "error" not in data
            )
    assert get.call_count == 2
