from fuzzywuzzy import fuzz
from fuzzywuzzy import process
from fuzzywuzzy import utils
from fuzzywuzzy.string_processing import StringProcessor


def test_basic_ratio_scores():
    assert fuzz.ratio("new york mets", "new york mets") == 100
    assert fuzz.partial_ratio("new york mets", "the new york mets") == 100


def test_token_scores_ignore_order():
    left = "new york mets vs atlanta braves"
    right = "atlanta braves vs new york mets"
    assert fuzz.token_sort_ratio(left, right) == 100
    assert fuzz.token_set_ratio(left, right) == 100


def test_full_process_normalizes_text():
    processed = utils.full_process("New York //// Mets $$$")
    assert processed.split() == ["new", "york", "mets"]
    assert utils.validate_string(processed) is True


def test_string_processor_replaces_symbols_with_spaces():
    processed = StringProcessor.replace_non_letters_non_numbers_with_whitespace("mets@braves")
    assert processed == "mets braves"


def test_process_extract_one_returns_best_choice():
    choices = ["new york jets", "new york giants", "liverpool"]
    match, score = process.extractOne("new york jets", choices)
    assert match == "new york jets"
    assert score == 100
