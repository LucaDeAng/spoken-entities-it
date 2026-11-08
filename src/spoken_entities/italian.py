"""Italian numbers and spelling, both ways.

Speaking: how a caller says a number or spells a code ("quarantacinquemila...",
"D come Domodossola"). Reading: turning what a speech recogniser wrote back into
digits and letters, for the rules extractor.
"""

from __future__ import annotations

import re
import unicodedata

UNITS = ["zero", "uno", "due", "tre", "quattro", "cinque", "sei", "sette", "otto", "nove", "dieci",
         "undici", "dodici", "tredici", "quattordici", "quindici", "sedici", "diciassette", "diciotto",
         "diciannove"]
TENS = {20: "venti", 30: "trenta", 40: "quaranta", 50: "cinquanta", 60: "sessanta", 70: "settanta",
        80: "ottanta", 90: "novanta"}

# The spelling alphabet Italian call centers use (cities; foreign letters by name).
SPELLING = {"A": "Ancona", "B": "Bologna", "C": "Como", "D": "Domodossola", "E": "Empoli", "F": "Firenze",
            "G": "Genova", "H": "hotel", "I": "Imola", "J": "jolly", "K": "kappa", "L": "Livorno",
            "M": "Milano", "N": "Napoli", "O": "Otranto", "P": "Palermo", "Q": "quarto", "R": "Roma",
            "S": "Savona", "T": "Torino", "U": "Udine", "V": "Venezia", "W": "Washington", "X": "ics",
            "Y": "ipsilon", "Z": "Zara"}
LETTER_NAMES = {"A": "a", "B": "bi", "C": "ci", "D": "di", "E": "e", "F": "effe", "G": "gi", "H": "acca",
                "I": "i", "J": "i lunga", "K": "kappa", "L": "elle", "M": "emme", "N": "enne", "O": "o",
                "P": "pi", "Q": "cu", "R": "erre", "S": "esse", "T": "ti", "U": "u", "V": "vu",
                "W": "doppia vu", "X": "ics", "Y": "ipsilon", "Z": "zeta"}
MONTHS = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre",
          "ottobre", "novembre", "dicembre"]


def _join(a: str, b: str) -> str:
    """Italian elides the final vowel before 'uno' and 'otto': ventuno, centotto, centottanta."""
    if b and b[0] in "uo" and a[-1] in "aeiou":
        return a[:-1] + b
    return a + b


def number_words(n: int) -> str:
    """0 <= n < 1,000,000 in words, as one Italian word: 45231 -> quarantacinquemiladuecentotrentuno."""
    if not 0 <= n < 1_000_000:
        raise ValueError(n)
    if n < 20:
        return UNITS[n]
    if n < 100:
        t, u = divmod(n, 10)
        if u == 3:
            return TENS[t * 10] + "tré"  # ventitré, trentatré
        return TENS[t * 10] if u == 0 else _join(TENS[t * 10], UNITS[u])
    if n < 1000:
        h, r = divmod(n, 100)
        head = "cento" if h == 1 else UNITS[h] + "cento"
        return head if r == 0 else _join(head, number_words(r))
    th, r = divmod(n, 1000)
    head = "mille" if th == 1 else number_words(th) + "mila"
    return head if r == 0 else head + number_words(r)


def digits_words(s: str) -> str:
    """'1042' -> 'uno, zero, quattro, due'."""
    return ", ".join(UNITS[int(c)] for c in s)


def spell(code: str) -> str:
    """'DLG7' -> 'D come Domodossola, L come Livorno, G come Genova, sette'."""
    parts = []
    for c in code:
        if c.isdigit():
            parts.append(UNITS[int(c)])
        elif c.isalpha():
            parts.append(f"{c.upper()} come {SPELLING[c.upper()]}")
    return ", ".join(parts)


def letters_plain(code: str) -> str:
    """'DLG7Q4K' -> 'di, elle, gi, sette, cu, quattro, kappa': letters by name, digits as words."""
    return ", ".join(UNITS[int(c)] if c.isdigit() else LETTER_NAMES[c.upper()] for c in code if c.isalnum())


# --- reading back ---------------------------------------------------------------

_NUM_MORPHEMES = sorted(
    [(w, v) for v, w in enumerate(UNITS)] + [(w, v) for v, w in TENS.items()]
    + [(w[:-1], v) for v, w in TENS.items()]  # elided: vent(uno), trent(otto)
    + [("tre", 3), ("cento", 100), ("cent", 100), ("mille", 1000), ("mila", 1000)],
    key=lambda x: -len(x[0]),
)


def _split(w: str, i: int = 0) -> list[int] | None:
    """Split a compound number word into morpheme values, backtracking over elisions."""
    if i == len(w):
        return []
    for m, v in _NUM_MORPHEMES:
        if w.startswith(m, i):
            rest = _split(w, i + len(m))
            if rest is not None:
                return [v] + rest
    return None


def parse_number_word(word: str) -> int | None:
    """Inverse of number_words for one compound word (accents stripped); None if not a number word."""
    parts = _split(word.lower()) if word else None
    if not parts:
        return None
    total, current = 0, 0
    for v in parts:
        if v == 100:
            current = (current or 1) * 100
        elif v == 1000:
            total += (current or 1) * 1000
            current = 0
        else:
            current += v
    return total + current


_CITY_TO_LETTER = {v.lower(): k for k, v in SPELLING.items()}
_NAME_TO_LETTER = {v: k for k, v in LETTER_NAMES.items() if " " not in v}


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


_MULTIPLIERS = ("cento", "cent", "mila", "mille")


def _joins(left: str, right: str) -> bool:
    """Would a speaker's single number word have been split here? 'cinquantasette mila',
    'mila novecento', 'novecento trentuno', 'cinquanta nove' yes; 'uno zero', 'sei cinque' no."""
    a, b = parse_number_word(left), parse_number_word(right)
    if a is None or b is None or b == 0:
        return False
    if right in ("mila", "mille", "cento") or (right.startswith("cento") and a < 10):
        return True  # 'cinquantasette mila', 'nove cento', 'nove centotrenta'
    if left.endswith(_MULTIPLIERS):
        return b < (1000 if left.endswith(("mila", "mille")) else 100)
    return a % 10 == 0 and 20 <= a % 100 <= 90 and b < 10  # 'cinquanta nove'


def _merge_split_numbers(tokens: list[str]) -> list[str]:
    """Rejoin number words the recogniser wrote apart. A comma (a spoken pause) blocks it, so
    digit-by-digit dictation ('uno, zero, quattro') stays apart."""
    out: list[str] = []
    for tok in tokens:
        low = tok.lower()
        if out and out[-1] not in ",;." and _joins(out[-1].lower(), low):
            out[-1] = out[-1].lower() + low
        else:
            out.append(tok)
    return out


def to_symbols(text: str) -> str:
    """What a rules-based normaliser makes of a transcript: one string of digits and capital letters.

    'D come Domodossola, L come Livorno' -> 'DL'; 'quarantacinque' -> '45'; 'C-1042' -> 'C1042'.
    Number words become digits, spelled letters become letters; everything else is dropped.
    """
    t = _strip_accents(text)
    t = re.sub(r"\bdoppia\s+vu\b", " W ", t, flags=re.IGNORECASE)  # two-word letter names
    t = re.sub(r"\bi\s+lunga\b", " J ", t, flags=re.IGNORECASE)
    # The letter written by name: "effe come Firenze" -> " F " (Scribe v2 with keyterms writes this)
    t = re.sub(rf"\b({'|'.join(n for n in _NAME_TO_LETTER if len(n) > 1)})\s+come\s+\w+",
               lambda m: f" {_NAME_TO_LETTER[m.group(1).lower()]} ", t, flags=re.IGNORECASE)
    # "D come Domodossola" -> " D ", also when the recogniser glues a digit on: "3D come Domodossola"
    t = re.sub(r"(?<![A-Za-z])([A-Za-z])\s+come\s+\w+", r" \1 ", t)
    out = []
    for tok in _merge_split_numbers(re.findall(r"[A-Za-z]+|\d+|[,;.]", t)):
        if tok in ",;.":
            continue
        low = tok.lower()
        if tok.isdigit():
            out.append(tok)
        elif (n := parse_number_word(low)) is not None:
            out.append(str(n))
        elif len(tok) == 1:
            out.append(tok.upper())
        elif low in _CITY_TO_LETTER:
            out.append(_CITY_TO_LETTER[low])
        elif low in _NAME_TO_LETTER:
            out.append(_NAME_TO_LETTER[low])
        elif tok.isupper():
            out.append(tok)  # an acronym-like run the recogniser already wrote as a code: DLG, IT
    return "".join(out)
