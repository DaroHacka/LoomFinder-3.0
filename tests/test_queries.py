import pytest
from loomfinder.queries import build_query_string


class TestBuildQueryString:
    def test_no_params_uses_random(self):
        url = build_query_string()
        assert "advancedsearch.php" in url
        assert "language:(eng)" in url

    def test_author_param(self):
        url = build_query_string(author="Dante")
        assert "creator:(Dante)" in url
        assert "language:(eng)" in url

    def test_title_and_author(self):
        url = build_query_string(title="Inferno", author="Dante")
        assert "title:(Inferno)" in url
        assert "creator:(Dante)" in url

    def test_date_range(self):
        url = build_query_string(start_date="1800", end_date="1820")
        assert "date:[1800-01-01%20TO%201820-12-31]" in url

    def test_subject_and_date(self):
        url = build_query_string(subject="history", start_date="1900", end_date="1950")
        assert "subject:(history)" in url

    def test_custom_language(self):
        url = build_query_string(subject="science", language="french")
        assert "language:(french)" in url

    def test_multi_word_author_uses_raw_string(self):
        url = build_query_string(author="Stephen King")
        assert "creator:(Stephen%20King)" in url

    def test_genre_uses_subject_field(self):
        url = build_query_string(genre="horror")
        assert "subject:(horror)" in url
        assert "genre:" not in url

    def test_page_param(self):
        url = build_query_string(subject="physics", page=3)
        assert "page=3" in url

    def test_default_page_is_1(self):
        url = build_query_string(subject="physics")
        assert "page=1" in url

    def test_returns_valid_url(self):
        url = build_query_string(subject="physics")
        assert url.startswith("https://archive.org/advancedsearch.php")
        assert "rows=1000" in url
        assert "output=json" in url
