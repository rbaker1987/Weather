"""Tests for application logging helpers."""

import asyncio
from pathlib import Path
from unittest.mock import patch

from weather.utils import logging as logging_utils


def test_setup_logging_adds_console_handler():
    with (
        patch.object(logging_utils.logger, "remove") as remove,
        patch.object(logging_utils.logger, "add") as add,
        patch.object(logging_utils.logger, "info") as info,
    ):
        logging_utils.setup_logging(log_level="DEBUG")

    remove.assert_called_once_with()
    assert add.call_count == 1
    assert add.call_args.args[0] is logging_utils.sys.stdout
    assert add.call_args.kwargs["level"] == "DEBUG"
    info.assert_called_once()


def test_setup_logging_adds_file_handler_and_creates_parent(tmp_path):
    log_path = tmp_path / "nested" / "weather.log"

    with (
        patch.object(logging_utils.logger, "remove"),
        patch.object(logging_utils.logger, "add") as add,
        patch.object(logging_utils.logger, "info"),
    ):
        logging_utils.setup_logging(log_file=str(log_path), rotation="daily", retention="1 week")

    assert log_path.parent.is_dir()
    assert add.call_count == 2
    assert add.call_args.args[0] == Path(log_path)
    assert add.call_args.kwargs["rotation"] == "daily"
    assert add.call_args.kwargs["retention"] == "1 week"


def test_get_logger_binds_name():
    with patch.object(logging_utils.logger, "bind", return_value="bound") as bind:
        assert logging_utils.get_logger("weather.api") == "bound"

    bind.assert_called_once_with(name="weather.api")


def test_log_helpers_delegate_to_logger():
    with (
        patch.object(logging_utils.logger, "debug") as debug,
        patch.object(logging_utils.logger, "info") as info,
        patch.object(logging_utils.logger, "error") as error,
    ):
        logging_utils.log_function_call("fetch", city="Austin", retry=1)
        logging_utils.log_api_request("https://example.test", params={"q": "x"})
        logging_utils.log_api_response("https://example.test", 200, response_time=0.25)
        logging_utils.log_api_response("https://example.test", 204)
        logging_utils.log_performance_metric("fetch", 1.234, cache_hit=True)
        logging_utils.log_error_with_context(ValueError("bad"), {"request_id": "1"})

    assert debug.call_count == 4
    info.assert_called_once()
    error.assert_called_once()
    assert "fetch(city=Austin, retry=1)" in debug.call_args_list[0].args[0]
    assert "0.25s" in debug.call_args_list[2].args[0]
    assert "204" in debug.call_args_list[3].args[0]


def test_log_calls_logs_success_and_reraises_errors():
    @logging_utils.log_calls
    def succeed(value):
        return value + 1

    @logging_utils.log_calls
    def fail():
        raise RuntimeError("broken")

    with patch.object(logging_utils.logger, "debug") as debug, patch.object(
        logging_utils.logger, "error"
    ) as error:
        assert succeed(4) == 5
        try:
            fail()
        except RuntimeError:
            pass
        else:
            raise AssertionError("expected RuntimeError")

    assert debug.call_count == 3
    error.assert_called_once()


def test_log_async_calls_logs_success_and_reraises_errors():
    @logging_utils.log_async_calls
    async def succeed(value):
        return value * 2

    @logging_utils.log_async_calls
    async def fail():
        raise RuntimeError("broken")

    async def run():
        with patch.object(logging_utils.logger, "debug") as debug, patch.object(
            logging_utils.logger, "error"
        ) as error:
            assert await succeed(3) == 6
            try:
                await fail()
            except RuntimeError:
                pass
            else:
                raise AssertionError("expected RuntimeError")
        return debug.call_count, error.call_count

    debug_count, error_count = asyncio.run(run())
    assert debug_count == 3
    assert error_count == 1
