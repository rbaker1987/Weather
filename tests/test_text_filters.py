"""Tests for weather template text filters."""

import pytest

from weather.templatetags.text_filters import truncate_smart


@pytest.mark.parametrize(
    ("text", "max_length", "expected"),
    [
        ("", 10, ""),
        ("Short text", 20, "Short text"),
        ("First sentence. Second sentence.", 20, "First sentence."),
        ("A reasonably long phrase without punctuation", 20, "A reasonably long..."),
        ("Supercalifragilisticexpialidocious", 10, "Supercalif..."),
    ],
)
def test_truncate_smart_handles_input_and_truncation_branches(
    text, max_length, expected
):
    assert truncate_smart(text, max_length) == expected


def test_truncate_smart_keeps_multiple_sentences_when_they_fit():
    text = "Sunny today. Clear tonight."

    assert truncate_smart(text, 30) == text
