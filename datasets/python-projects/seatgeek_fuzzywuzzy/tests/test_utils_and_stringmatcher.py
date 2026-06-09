from fuzzywuzzy import utils
from fuzzywuzzy.string_processing import StringProcessor


def test_validate_string_and_type_consistency():
    assert utils.validate_string("abc") is True
    assert utils.validate_string(None) is False
    assert utils.make_type_consistent("abc", "def") == ("abc", "def")


def test_full_process_and_ascii_helpers():
    assert utils.asciidammit("hello") == "hello"
    assert utils.full_process(" This is Unicode!   ") == "this is unicode"
    assert utils.full_process("   ") == ""


def test_string_processor_case_and_strip():
    value = "  Hello\n"
    assert StringProcessor.strip(value) == "Hello"
    assert StringProcessor.to_lower_case(value) == value.lower()
    assert StringProcessor.to_upper_case(value) == value.upper()


def test_intr_rounds_scores():
    assert utils.intr(99.6) == 100
    assert utils.intr(42.2) == 42
