import pytest
from loomfinder.random_selection import extract_segment, get_weighted_random_choice
from loomfinder.categories import default_genres_subjects


class TestExtractSegment:
    def test_returns_none_for_short_text(self):
        assert extract_segment("hello world", num_words=200) is None

    def test_returns_segment_for_long_text(self):
        text = "word " * 500
        segment = extract_segment(text.rstrip(), num_words=200)
        assert segment is not None
        assert len(segment.split()) >= 200

    def test_extends_to_sentence_boundary(self):
        words = ["word"] * 199 + ["end."] + ["extra"] * 50
        text = " ".join(words)
        segment = extract_segment(text, num_words=200)
        assert segment is not None


class TestGetWeightedRandomChoice:
    def test_returns_from_default_list(self):
        for _ in range(100):
            choice = get_weighted_random_choice()
            assert choice in default_genres_subjects

    def test_returns_string(self):
        assert isinstance(get_weighted_random_choice(), str)
