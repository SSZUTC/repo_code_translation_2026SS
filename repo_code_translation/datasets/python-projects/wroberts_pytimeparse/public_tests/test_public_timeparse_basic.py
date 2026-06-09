from pytimeparse.timeparse import timeparse


def test_public_clock_and_units():
    assert timeparse("3:05") == 185
    assert timeparse("2 minutes 5 seconds") == 125


def test_public_fraction_and_sign():
    assert timeparse("0.5 hours") == 1800
    assert timeparse("- 30 seconds") == -30


def test_public_invalid_input():
    assert timeparse("duration unknown") is None
