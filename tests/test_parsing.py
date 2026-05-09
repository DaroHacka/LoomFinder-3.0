import pytest
from loomfinder.parsing import parse_parameters


class TestParseParameters:
    def test_all_params(self):
        params = [
            "t:The Great Gatsby",
            "g:novel",
            "x:fiction",
            "a:F. Scott Fitzgerald",
            "s:literature",
            "d:1920-1930",
        ]
        result = parse_parameters(params)
        assert result == (
            "The Great Gatsby",
            "novel",
            "fiction",
            "F. Scott Fitzgerald",
            "literature",
            "1920-1930",
        )

    def test_partial_params(self):
        result = parse_parameters(["a:Dante", "d:1300-1400"])
        assert result == (None, None, None, "Dante", None, "1300-1400")

    def test_empty_params(self):
        result = parse_parameters([])
        assert result == (None, None, None, None, None, None)

    def test_prose_not_parsed(self):
        result = parse_parameters(["prose"])
        assert result == (None, None, None, None, None, None)

    def test_date_range(self):
        result = parse_parameters(["d:1800-1805"])
        assert result[5] == "1800-1805"
