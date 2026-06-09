from fuzzywuzzy import fuzz
from fuzzywuzzy import process
from fuzzywuzzy import utils


def test_public_ratio_and_partial_ratio():
    assert fuzz.ratio("san francisco giants", "san francisco giants") == 100
    assert fuzz.partial_ratio("san francisco giants", "the san francisco giants") == 100


def test_public_token_ratios():
    left = "san francisco giants vs los angeles dodgers"
    right = "los angeles dodgers vs san francisco giants"
    assert fuzz.token_sort_ratio(left, right) == 100
    assert fuzz.token_set_ratio(left, right) == 100


def test_public_utils_full_process():
    assert utils.full_process("SAN FRANCISCO!!! Giants").split() == ["san", "francisco", "giants"]


def test_public_extract_best_match():
    choices = ["java developer", "python engineer", "c++ guru"]
    match, score = process.extractOne("python programmer", choices)
    assert match in choices
    assert isinstance(score, int)
    assert score > 0
