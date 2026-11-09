import sys, pathlib, os
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
os.environ.setdefault("KNOWLEDGE_PATH",
                      str(pathlib.Path(__file__).resolve().parent.parent
                          / "fixtures" / "knowledge.demo.json"))
from datetime import datetime
from app import nlq


def test_single_year_is_a_range_not_open_ended():
    f = nlq.parse("ECFR articles from 2024 about China")["filter"]
    assert f["published_at"]["$gte"] == datetime(2024, 1, 1)
    assert f["published_at"]["$lt"] == datetime(2025, 1, 1)


def test_since_is_open_ended():
    f = nlq.parse("documents since 2025")["filter"]
    assert "$lt" not in f["published_at"]


def test_year_range():
    f = nlq.parse("policy briefs 2022-2024")["filter"]
    assert f["published_at"]["$gte"].year == 2022
    assert f["published_at"]["$lt"].year == 2025


def test_institution_and_multiple_institutions():
    assert nlq.parse("ECFR on China")["filter"]["think_tank"] == "ECFR"
    got = nlq.parse("Elcano and Bruegel policy briefs")["filter"]["think_tank"]["$in"]
    assert set(got) == {"Elcano", "Bruegel"}


def test_quoted_phrase_becomes_a_term():
    r = nlq.parse('documents mentioning "de-risking"')
    assert "de-risking" in r["terms"]


def test_reliable_dates_excludes_the_right_institutions():
    f = nlq.parse("documents with reliable dates")["filter"]
    assert set(f["think_tank"]["$nin"]) == {"FES (Friedrich-Ebert-Stiftung)", "PRIO"}


def test_every_clause_is_explained():
    r = nlq.parse("ECFR policy briefs since 2024 about semiconductors")
    clauses = {e["clause"] for e in r["explain"]}
    assert {"think_tank", "published_at", "publication_group"} <= clauses
    assert all(e.get("note") for e in r["explain"])


def test_output_always_passes_the_safety_validator():
    from app.safety import validate_filter
    for q in ["ECFR 2024", 'find "strategic autonomy" since 2023',
              "top 10 reports with pdf", "$where sleep", "{'$out': 'x'}"]:
        validate_filter(nlq.parse(q)["filter"])
