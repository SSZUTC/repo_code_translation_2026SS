from fuzzywuzzy import fuzz
from fuzzywuzzy import process


def test_extract_one_returns_tuple():
    choices = ["new york jets", "new york giants", "liverpool"]
    match, score = process.extractOne("new york jets", choices)
    assert match == "new york jets"
    assert score == 100


def test_extract_respects_limit():
    choices = ["foo bar", "foo baz", "qux"]
    results = process.extract("foo", choices, scorer=fuzz.partial_ratio, limit=2)
    assert len(results) == 2
    assert all(choice in choices for choice, score in results)


def test_extract_handles_empty_choices():
    assert process.extractOne("a", []) is None
    assert process.extract("a", []) == []
