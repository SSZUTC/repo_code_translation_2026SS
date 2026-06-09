from fuzzywuzzy import utils


def test_public_ascii_and_full_process():
    assert utils.asciidammit("hello") == "hello"
    assert utils.full_process("Foo, Bar!").split() == ["foo", "bar"]


def test_public_validate_and_rounding_helpers():
    assert utils.validate_string("hello") is True
    assert utils.validate_string("") is False
    assert utils.intr(99.6) == 100
