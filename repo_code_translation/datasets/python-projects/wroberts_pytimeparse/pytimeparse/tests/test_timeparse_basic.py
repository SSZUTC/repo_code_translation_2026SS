from pytimeparse.timeparse import timeparse


def test_clock_formats():
    assert timeparse("1:24") == 84
    assert timeparse(":22") == 22
    assert timeparse("1:02:03") == 3723


def test_unit_formats():
    assert timeparse("1 minute, 24 secs") == 84
    assert timeparse("1m24s") == 84
    assert timeparse("2 hours 30 minutes") == 9000


def test_fractional_values():
    assert timeparse("1.5 minutes") == 90
    assert timeparse("1.2 seconds") == 1.2


def test_signed_values():
    assert timeparse("- 1 minute") == -60
    assert timeparse("+ 1 minute") == 60


def test_minute_granularity_for_ambiguous_clock():
    assert timeparse("1:30") == 90
    assert timeparse("1:30", granularity="minutes") == 5400


def test_invalid_values_return_none():
    assert timeparse("not a duration") is None
    assert timeparse("") is None
