from fuzzywuzzy import process


def test_public_extract_one():
    choices = ["java developer", "python engineer", "c++ guru"]
    match, score = process.extractOne("python programmer", choices)
    assert match in choices
    assert isinstance(score, int)
    assert score > 0


def test_public_extract_bests_limit():
    choices = ["science data", "data analytics", "data scientist", "big data"]
    results = process.extractBests("data science", choices, limit=2)
    assert len(results) == 2
