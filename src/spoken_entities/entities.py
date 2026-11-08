"""The entities an Italian utility's voice agent has to catch, synthetic and unassignable.

Eight types, each with a validator. Two validators are real checksums (IBAN mod-97,
codice fiscale check letter), so a wrong value is usually caught and the agent can
ask again. The others only check the format, so a wrong value passes silently.

No value can belong to anyone: fiscal codes use the place code Y999, which no
municipality or country has; IBANs use bank and branch 99999; PODs use
distributor 999.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from datetime import date

from spoken_entities.italian import (
    MONTHS,
    digits_words,
    letters_plain,
    number_words,
    spell,
)

# --- validators -------------------------------------------------------------------


def iban_ok(v: str) -> bool:
    v = v.replace(" ", "").upper()
    if not re.fullmatch(r"IT\d{2}[A-Z]\d{10}[A-Z0-9]{12}", v):
        return False
    moved = v[4:] + v[:4]
    return int("".join(str(int(c, 36)) for c in moved)) % 97 == 1


_CF_ODD = dict(zip("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ",
                   [1, 0, 5, 7, 9, 13, 15, 17, 19, 21, 1, 0, 5, 7, 9, 13, 15, 17, 19, 21, 2, 4, 18, 20, 11, 3, 6, 8,
                    12, 14, 16, 10, 22, 25, 24, 23]))
_CF_EVEN = {c: (int(c) if c.isdigit() else ord(c) - 65) for c in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"}


def cf_check_letter(first15: str) -> str:
    s = sum(_CF_ODD[c] if i % 2 == 0 else _CF_EVEN[c] for i, c in enumerate(first15.upper()))
    return chr(65 + s % 26)


def cf_ok(v: str) -> bool:
    v = v.upper()
    return bool(re.fullmatch(r"[A-Z]{6}\d{2}[A-EHLMPRST]\d{2}[A-Z]\d{3}[A-Z]", v)) and cf_check_letter(v[:15]) == v[15]


def date_ok(v: str) -> bool:
    try:
        d = date.fromisoformat(v)
    except (ValueError, TypeError):
        return False
    return 1920 <= d.year <= 2008


VALIDATORS = {
    "customer_code": lambda v: bool(re.fullmatch(r"C-\d{4}", v)),
    "delegation_ref": lambda v: bool(re.fullmatch(r"DLG-[A-Z0-9]{4}", v)),
    "birth_date": date_ok,
    "meter_reading": lambda v: bool(re.fullmatch(r"\d{5}", v)),
    "amount": lambda v: bool(re.fullmatch(r"\d{1,4},\d{2}", v)),
    "pod": lambda v: bool(re.fullmatch(r"IT\d{3}E\d{8}", v)),
    "iban": iban_ok,
    "fiscal_code": cf_ok,
}
CHECKSUM = {"iban", "fiscal_code"}  # validators that catch most single-symbol errors

# How each type is introduced in the call: the caller's sentence before the value.
FRAMES = {
    "customer_code": "Il mio codice cliente è",
    "delegation_ref": "Il codice di delega è",
    "birth_date": "La data di nascita del titolare è il",
    "meter_reading": "La lettura del contatore è",
    "amount": "L'importo che ho pagato è",
    "pod": "Il codice POD è",
    "iban": "L'IBAN per l'addebito è",
    "fiscal_code": "Il codice fiscale è",
}

# --- spoken forms -----------------------------------------------------------------


def _spoken_date(iso: str, style: str) -> str:
    d = date.fromisoformat(iso)
    if style == "natural":
        day = "primo" if d.day == 1 else number_words(d.day)
        return f"{day} {MONTHS[d.month - 1]} {number_words(d.year)}"
    return f"{number_words(d.day)}, {number_words(d.month)}, {number_words(d.year)}"


def _grouped(digits: str, size: int) -> str:
    """'45231' grouped by 2 from the left as people read numbers: 'quarantacinque, ventitré, uno'."""
    groups = [digits[i:i + size] for i in range(0, len(digits), size)]
    return ", ".join(digits_words(g) if g.startswith("0") else number_words(int(g)) for g in groups)


def spoken(etype: str, value: str, style: str) -> str:
    """What the caller says after the frame. 'natural' is how most people say it;
    'spelled' is digit by digit, letters with the city alphabet."""
    if etype == "birth_date":
        return _spoken_date(value, style)
    if etype == "amount":
        euro, cents = value.split(",")
        if style == "natural":
            return f"{number_words(int(euro))} euro e {number_words(int(cents))} centesimi"
        return f"{digits_words(euro)}, virgola, {digits_words(cents)}, euro"
    if etype == "meter_reading":
        return number_words(int(value)) if style == "natural" else digits_words(value)
    raw = value.replace("-", "")
    if style == "spelled":
        return spell(raw)
    # natural: letters by name, digits in pairs or as words
    if etype == "customer_code":
        return f"ci, {_grouped(raw[1:], 2)}"
    if etype in ("iban", "pod"):
        return ", ".join(letters_plain(c) if c.isalpha() else _grouped(c, 2)
                         for c in re.findall(r"[A-Z]+|\d+", raw))
    return letters_plain(raw)  # delegation_ref, fiscal_code


def clip_text(etype: str, value: str, style: str) -> str:
    return f"{FRAMES[etype]} {spoken(etype, value, style)}."


# --- the synthetic set --------------------------------------------------------------


@dataclass(frozen=True)
class Entity:
    id: str
    type: str
    value: str
    # "v1": the first IBANs and fiscal codes, unassignable through artificial patterns (ten nines in
    # a row, place code Y999) that turned out to drive most recognition errors. "v2": realistic
    # patterns, unassignable through a field no real code can have. Other types are the same in both.
    version: str = "v1"


def _iban(rng: random.Random) -> str:
    cin = rng.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    bban = f"{cin}9999999999{rng.randrange(10**12):012d}"
    for check in range(100):
        cand = f"IT{check:02d}{bban}"
        if iban_ok(cand):
            return cand
    raise AssertionError("no IBAN check digits")


def _cf(rng: random.Random) -> str:
    letters = "BCDFGLMNPRSTVZ"
    head = "".join(rng.choice(letters) for _ in range(6))
    year = rng.randrange(40, 99)
    month = rng.choice("ABCDEHLMPRST")
    day = rng.randrange(1, 29) + rng.choice([0, 40])
    body = f"{head}{year:02d}{month}{day:02d}Y999"
    return body + cf_check_letter(body)


def italian_cin(abi_cab_account: str) -> str:
    """The national check letter of an Italian BBAN (ABI + CAB + account). It uses the same odd/even
    tables as the fiscal code's check letter."""
    return cf_check_letter(abi_cab_account)


def _iban_v2(rng: random.Random) -> str:
    """Realistic digits, but a CIN that is deliberately wrong: the IBAN check digits (mod-97) are
    valid, the national check letter is not, so no bank can have issued it."""
    rest = f"0{rng.randrange(10**4):04d}{rng.randrange(10**5):05d}{rng.randrange(10**12):012d}"
    right = italian_cin(rest)
    cin = chr(65 + (ord(right) - 65 + rng.randrange(1, 26)) % 26)
    bban = cin + rest
    for check in range(100):
        cand = f"IT{check:02d}{bban}"
        if iban_ok(cand):
            return cand
    raise AssertionError("no IBAN check digits")


# Real place codes of large municipalities: Roma, Milano, Napoli, Torino, Palermo, Bologna, Firenze, Bari.
PLACES = ["H501", "F205", "F839", "L219", "G273", "A944", "D612", "A662"]


def _cf_v2(rng: random.Random) -> str:
    """A real place code, but a day of birth of 32-40: no one is born on day 32-40 (women are
    41-71), so the code cannot belong to anyone. The check letter is computed as usual."""
    letters = "BCDFGLMNPRSTVZ"
    head = "".join(rng.choice(letters) for _ in range(6))
    body = f"{head}{rng.randrange(40, 99):02d}{rng.choice('ABCDEHLMPRST')}{rng.randrange(32, 41):02d}{rng.choice(PLACES)}"
    return body + cf_check_letter(body)


def build_set(per_type: int = 4, seed: int = 7) -> list[Entity]:
    rng = random.Random(seed)
    alnum = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no I/O/0/1 in delegation codes
    out: list[Entity] = []
    for i in range(per_type):
        n = i + 1
        out += [
            Entity(f"customer_code-{n}", "customer_code", f"C-{rng.randrange(1000, 10000)}"),
            Entity(f"delegation_ref-{n}", "delegation_ref", "DLG-" + "".join(rng.choice(alnum) for _ in range(4))),
            Entity(f"birth_date-{n}", "birth_date",
                   date(rng.randrange(1940, 2000), rng.randrange(1, 13), rng.randrange(1, 29)).isoformat()),
            Entity(f"meter_reading-{n}", "meter_reading", f"{rng.randrange(10000, 100000)}"),
            Entity(f"amount-{n}", "amount", f"{rng.randrange(20, 400)},{rng.randrange(0, 100):02d}"),
            Entity(f"pod-{n}", "pod", f"IT999E{rng.randrange(10**8):08d}"),
            Entity(f"iban-{n}", "iban", _iban(rng)),
            Entity(f"fiscal_code-{n}", "fiscal_code", _cf(rng)),
        ]
    rng2 = random.Random(seed + 1)  # a separate stream, so the v1 values above never change
    for i in range(per_type):
        out += [Entity(f"iban-r{i + 1}", "iban", _iban_v2(rng2), "v2"),
                Entity(f"fiscal_code-r{i + 1}", "fiscal_code", _cf_v2(rng2), "v2")]
    for e in out:
        assert VALIDATORS[e.type](e.value), e
    return out
