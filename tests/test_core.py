import pytest

from spoken_entities.entities import (
    CHECKSUM,
    PLACES,
    VALIDATORS,
    build_set,
    cf_ok,
    clip_text,
    iban_ok,
    italian_cin,
)
from spoken_entities.italian import number_words, parse_number_word, to_symbols
from spoken_entities.pipeline import rules_extract
from spoken_entities.score import outcome, wilson


def test_number_words_round_trip():
    for n in range(0, 100_000, 7):
        assert parse_number_word(number_words(n).replace("é", "e")) == n, n


@pytest.mark.parametrize("n,words", [(21, "ventuno"), (23, "ventitré"), (108, "centotto"), (180, "centottanta"),
                                     (1000, "mille"), (45231, "quarantacinquemiladuecentotrentuno")])
def test_number_words_elision(n, words):
    assert number_words(n) == words


def test_synthetic_values_are_valid_and_unassignable():
    es = build_set()
    assert len(es) == 40  # 32 v1 values + 4 v2 IBANs + 4 v2 fiscal codes
    for e in es:
        assert VALIDATORS[e.type](e.value)
        if e.type == "pod":
            assert e.value.startswith("IT999E")
        if e.version == "v1" and e.type == "fiscal_code":
            assert e.value[11:15] == "Y999"
        if e.version == "v1" and e.type == "iban":
            assert e.value[5:15] == "9999999999"
        if e.version == "v2" and e.type == "fiscal_code":
            assert 32 <= int(e.value[9:11]) <= 40 and e.value[11:15] in PLACES  # no one is born on day 32-40
        if e.version == "v2" and e.type == "iban":
            assert italian_cin(e.value[5:]) != e.value[4]  # mod-97 valid, national check letter wrong


def test_checksums_catch_a_single_changed_symbol():
    es = {e.type: e.value for e in build_set()}
    iban, cf = es["iban"], es["fiscal_code"]
    assert not iban_ok(iban[:-1] + ("1" if iban[-1] != "1" else "2"))
    assert not cf_ok(cf[:6] + ("1" if cf[6] != "1" else "2") + cf[7:])
    assert CHECKSUM == {"iban", "fiscal_code"}


def test_to_symbols_handles_recogniser_quirks():
    assert to_symbols("D come Domodossola, L come Livorno, G come Genova, sette") == "DLG7"
    assert to_symbols("K come Cappa, 3D come Domodossola") == "K3D"  # digit glued to the letter
    assert to_symbols("IT 63 G 9999") == "IT63G9999"
    # Scribe v2 with keyterms writes the letter by name before "come": one letter, not two
    assert to_symbols("effe come Firenze, ti come Torino, nove uno") == "FT91"
    assert to_symbols("doppia vu come Washington, i lunga come jolly") == "WJ"


@pytest.mark.parametrize("style", ["natural", "spelled"])
def test_rules_extractor_reads_the_clean_text(style):
    """On the TTS input text (no recognition errors) the rules extractor gets every value right."""
    for e in build_set():
        assert rules_extract(e.type, clip_text(e.type, e.value, style)) == e.value, (e, style)


def test_outcomes():
    assert outcome("meter_reading", "45231", "45231", False) == "correct"
    assert outcome("meter_reading", "45231", "45213", False) == "silent"
    assert outcome("meter_reading", "45231", "45213", True) == "re-ask"
    assert outcome("meter_reading", "45231", "45231", True) == "re-ask"  # right but unsure: still asks
    assert outcome("meter_reading", "45231", "4521", False) == "re-ask"
    assert outcome("meter_reading", "45231", None, False) == "re-ask"


def test_wilson_interval():
    lo, hi = wilson(0, 128)
    assert lo == 0 and 0.02 < hi < 0.04


@pytest.mark.parametrize("text,symbols", [
    ("cinquantasette mila novecento trentuno", "57931"),  # the recogniser split one word into four
    ("mille novecento ottanta cinque", "1985"),
    ("uno, zero, quattro", "104"),  # a pause between digits keeps them apart
    ("sei cinque zero", "650"),     # digits without pauses stay digits too
])
def test_split_number_words_are_rejoined(text, symbols):
    assert to_symbols(text) == symbols


def test_score_runs_from_cached_data_without_keys(monkeypatch):
    """CI rebuilds docs/results.md from data/ alone."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    from spoken_entities.score import report, rows
    rs = rows()
    if not rs:
        pytest.skip("no cached transcripts")
    assert {r["outcome"] for r in rs} <= {"correct", "re-ask", "silent"}
    assert "# Results" in report(rs)
