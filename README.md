# spoken-entities-it

**When an Italian voice agent mishears a customer code, an IBAN or a meter reading, does it notice?**

A voice agent on an Italian utility line has to catch values read aloud: customer codes, delegation
codes, birth dates, meter readings, amounts, POD codes, IBANs, fiscal codes. A misheard value that
fails a check is cheap: the agent asks again. A misheard value that passes is the expensive one,
because the agent acts on it: the wrong account is looked up, the wrong reading is billed. This repo measures
that second case, which I call **silent wrong**, through a real speech pipeline.

## Setup

```
32 synthetic values × 2 ways of saying them × 2 voices × 3 channels = 384 recordings (+96 for the v1 comparison)
each recording through 3 recogniser set-ups: Scribe v1, Scribe v2, Scribe v2 + keyterms
text ─► ElevenLabs TTS ─► channel ─► ElevenLabs Scribe ─► extractor ─► validator ─► outcome
```

- **Values.** Eight entity types for Brezzaluce Energia, the fictional utility of
  [deployment-in-a-box](https://github.com/LucaDeAng/deployment-in-a-box), four values each, none
  assignable to anyone ([`entities.py`](src/spoken_entities/entities.py)):
  - **v2 IBANs** have realistic digits and a national check letter (CIN) that is deliberately wrong:
    the IBAN check digits pass, no bank can have issued it;
  - **v2 fiscal codes** use a real place code (Roma, Milano...) and a day of birth of 32–40, which
    nobody has;
  - PODs use distributor `999`.

  The first version, v1, made IBANs and fiscal codes unassignable with ten nines in a row and the
  place code `Y999`. Those patterns caused most of v1's errors, so v1 is kept only as a comparison.
- **Ways of saying them.** *natural* is one common way to say it: "ci, sessantatré, zero, cinque";
  "centottanta euro e cinquantanove centesimi". *spelled* is digit by digit, with letters in the
  telephone alphabet of city names: "D come Domodossola".
- **Voices.** An ElevenLabs default voice (English-native) speaking Italian, and a native Italian
  voice from the public library, both on `eleven_flash_v2_5`. They play the caller.
- **Channels.** The clean TTS file; a phone line (8 kHz, 300–3400 Hz, G.711 μ-law, via ffmpeg); the
  same line with one mild level of pink noise.
- **Recognition.** ElevenLabs Scribe, batch, Italian. The headline tables use `scribe_v1` without
  keyterms; the [recogniser comparison](#recogniser) runs the same audio through `scribe_v2`, with
  and without keyterms.
- **Extractors.** A deterministic rules normaliser ([`italian.py`](src/spoken_entities/italian.py)) and
  Claude Haiku 5.5 and Opus 5.5 with structured output (one run each, `effort: low`), which may
  return null or mark a value unsure.
- **Validators.** IBAN mod-97 and the fiscal-code check letter are real checksums. The other six types
  only have a format check.
- **Outcomes.**
  - **correct:** the value is right and the extractor is sure of it;
  - **re-ask:** no value, marked unsure (even when right), or rejected by the validator, so the agent asks again;
  - **silent wrong:** a wrong value that passes the validator and is not marked unsure, so the agent acts on it.

## Results

Full tables, v1 against v2, and every wrong value with what caught it: [docs/results.md](docs/results.md).
Each extractor saw 384 recordings, all through Scribe v1 (v2 IBANs and fiscal codes, the other six
types as they are; below, v1 and v2 are the two sets of test values, not the recogniser).

| extractor | right first time | re-ask: right but unsure | re-ask: other | silent wrong |
|---|---|---|---|---|
| rules | 97% | 0% | 3% | 0 |
| Claude Haiku 5.5 | 83% | 5% | 11% | 0 |
| Claude Opus 5.5 | 86% | 12% | 2% | 0 |

0 of 384 is 128 distinct recordings through three channels that mostly agree, so the 95% upper
bound is about 3%.

- **No wrong value got through with Scribe v1.** That is the number that costs money, and it held
  for every extractor; with Scribe v2 it did not quite (see [Recogniser](#recogniser)). On synthetic speech it says the mechanism works, not what the rate is on real callers.
- **Opus doubts right answers, and the checksum can settle it.** Opus marked 41 of 48 fiscal codes
  unsure, 38 of them right. If a value that passes the checksum is accepted even when marked unsure,
  Opus goes from 86% to 97% right first time and Haiku from 83% to 86%, with no wrong value let
  through. I found this rule on v1 and it held on v2, which it had not seen: on v2's IBANs and fiscal
  codes Opus went from 50 to 90 of 96. On this set only: a fiscal code's check letter accepts about
  1 in 26 random corruptions, an IBAN's mod-97 about 1 in 97, so the overlap between the extractor's
  doubt and the validator should be designed, not assumed.
- **When the checksum mattered, it mattered a lot.** On the v2 values, the rules normaliser and Opus produced no
  wrong IBAN or fiscal code. Haiku produced four, and two of them were sure and well formed: "K come
  kappa" came back from the recogniser as a nonsense word starting with C, Haiku wrote C, and mod-97
  rejected the IBAN. With only a format check, the agent would have acted on both.
- **My first test values were most of the problem.** Moving IBANs and fiscal codes from v1 to v2 took the
  rules normaliser from 50% to 91% right on them. On v1, 19 of its 20 wrong values sat on the `Y` of
  `Y999` or on the run of nines. They were all caught by the checksum; with only a format check the
  agent would have acted on 20 of 96. A benchmark's synthetic values can shape its results as much as the system it tests.
- **Haiku is cautious where it shouldn't be.** It got 17 of 48 delegation codes right and was sure
  of 11, where rules and Opus got 46. On "di LGK3DE" it returned nothing instead of reading "di" as D.
- **Asking the caller to spell works** (v1 values). Of the 23 natural IBANs the rules normaliser
  missed, the spelled version of the same value came through right in 18.
- **The phone line did not separate anything.** Right first time moved by at most five points
  between channels, in no consistent direction. Synthetic voices are clear and steady, the noise
  was mild, and a real caller is neither.

## Recogniser

The same 384 recordings through Scribe v2, once plain and once with 42
[keyterms](https://elevenlabs.io/docs/eleven-api/guides/how-to/speech-to-text/batch/keyterm-prompting): the spelling-alphabet words, the Italian letter names of three letters or
more (effe, erre, zeta...) and the field names ("codice fiscale", "IBAN"...). Never a test value:
keyterms tell the recogniser what kind of words to expect, not what the answer is. They add about
a fifth to the price of recognition ($0.05 on $0.22 an hour at the
[API list price](https://elevenlabs.io/pricing/api), November 2026).

| extractor | Scribe v1 | Scribe v2 | Scribe v2 + keyterms |
|---|---|---|---|
| rules | 97% · 0 silent | 95% · 2 silent | 98% · 0 silent |
| Claude Haiku 5.5 | 83% · 0 | 84% · 1 | 84% · 1 |
| Claude Opus 5.5 | 86% · 0 | 86% · 1 | 86% · 0 |

Right first time and silent wrongs, n = 384 per cell. Full tables in
[docs/results.md](docs/results.md#recogniser).

- **Changing the recogniser moved accuracy by a few points, within the noise.** The extractors
  differ from each other far more than the recognisers do.
- **The zero did not carry over, and the misses landed where there is no checksum.** Five silent
  wrongs across the 2,304 Scribe v2 extractions, from three recordings, all on delegation codes and
  PODs, which only have a format check. None on IBANs or fiscal codes. This is not evidence that
  Scribe v2 is worse (0 in 1,152 against 5 in 2,304 is within chance); it is evidence that a zero
  measured on one recogniser does not transfer to another, so the check has to re-run on every
  recogniser change.
- **Across all nine set-ups, the checksum held.** 9 wrong IBANs and fiscal codes, none acted on;
  on the format-only codes, 5 of 8 wrong values got through. Accepting a checksum-valid value
  despite the unsure flag replicated on both Scribe v2 set-ups (Opus 96–97%, Haiku 86–87% right
  first time) and never accepted a wrong value.
- **One recogniser error got past every extractor.** For `DLG-GEDP` on the clean channel, Scribe
  v2 wrote "DLGDEDP": a G heard as D, the length kept. Rules, Haiku and Opus all returned
  `DLG-DEDP`, sure of it. Scribe v1 and Scribe v2 with keyterms dropped a letter on the same
  audio instead ("di LGEDP"): every extractor returned nothing or marked it unsure, and the
  agent would have asked again. An error that keeps the format is the one only a read-back or a checksum can catch.
- **Not every silent wrong is the recogniser's.** With keyterms, Haiku turned a correctly
  transcribed POD ("cinque-sei-cinque...") into `...65599395`, swapping two digits, and was sure.
  And the rules normaliser turned a transcript with one extra letter ("DLGI di 3DQ") into
  `DLG-ID3D` by keeping the first four symbols; it should have rejected the surplus. Not fixed, so
  that the numbers above stay the ones the parser produced before seeing Scribe v2.
- **Keyterms changed how Scribe writes spelling, and that broke my parser.** With keyterms,
  23 transcripts wrote the letter by name before "come" ("effe come Firenze"), which the rules
  normaliser read as two letters. On that set-up it scored 92% right first time until I added
  that pattern, and 98% after; Scribe v1 stays at 97% either way. The fix came from one clip of this condition, so the 98% is not held-out;
  the Scribe v1 results are unchanged by it. A normaliser written against one recogniser's output
  is part of what a recogniser change tests.

## How this relates to τ-Entity

Sierra's [τ-Entity](https://sierra.ai/blog/tau-entity-can-voice-agents-get-the-details-right)
(October 2026) tests whether whole voice agents capture, verify and repair entities over a call,
in six languages; Italian is not one of them. The companion paper is
[τ-Elicitation](https://arxiv.org/abs/2609.13602). This repo is narrower: one recognition and
extraction pass and what the validator does with it, no repair over turns.

## Limits

- **Synthetic speech only.** Two TTS voices, no accents, no hesitation, no self-correction ("no
  scusi, sette"). The pipeline is ready for recorded human speech; the numbers above are not a
  forecast for it.
- **The unassignable fields are invisible to my validators.** A v2 IBAN has a wrong CIN and a v2 fiscal code an
  impossible day; a production validator that also checks those would reject my test values before
  the checksum. I use only mod-97 and the check letter.
- **Synthesis and recognition errors are only partly separated.** On v1 a transcript reading "I come
  ipsilon" suggests the TTS read Y as "i". Where two Scribe versions disagree on the same audio
  the error is the recogniser's, but both are ElevenLabs models, and I have not listened to every
  failing clip.
- **Small, correlated cells.** Each type has 16 distinct recordings (8 texts × 2 voices), and the
  three channels gave the same outcome for most of them. A 0 in one type means under about 1 in 5.
  The Wilson intervals in docs/results.md assume independence and are too narrow.
- **The rules extractor was fixed on v1 transcripts.** It did not rejoin number words that Scribe
  split ("cinquantasette mila novecento trentuno"), read "3D come Domodossola" as two D's, and
  read "doppia vu" as V; with those bugs it let two wrong values through. v2's IBANs and fiscal codes
  came later and act as a small held-out check (91% right, no wrong value), but the other six types
  were scored on the same transcripts it was fixed on. The Claude prompt was written once and not changed.
- **One vendor, one run, batch.** Three Scribe set-ups from one vendor, none of them the streaming
  recogniser a live agent uses; each recognition and each Claude extraction (at `effort: low`)
  ran once, so a difference of one or two values between set-ups is not a finding.
- **Amounts, dates and readings have no checksum**, so for them a misheard value that keeps its
  format can only be caught by reading it back to the caller. In this set every one was recovered.

## Next

- The streaming recogniser a live agent would use (Scribe v2 Realtime; the 42 keyterms fit its
  limits unchanged) and a recogniser from a second vendor, on the same audio.
- Make the rules normaliser reject surplus symbols instead of keeping the first ones.
- Harder channels (lower SNR, a narrowband mobile codec) and consented human recordings, with the
  failing clips committed so they can be heard.
- Repair, not just re-ask: re-asking the same audio repeats the same error, so switch how the
  caller gives the value (spelled, keypad) and measure how often the second try lands.
- Cost per outcome: a re-ask costs a turn, a silent wrong a complaint and a rebill. The
  [business case calculator](https://genai4business.com/tools/business-case) is where those meet.

## Run it

```bash
uv sync
uv run pytest -q                                  # no keys needed
uv run python -m spoken_entities.score            # rebuild docs/results.md from data/, no keys
```

Regenerating the data needs `ELEVENLABS_API_KEY` and `ANTHROPIC_API_KEY` (environment, or
`~/.secrets/{elevenlabs,anthropic}.env`):

```bash
uv run python -m spoken_entities.pipeline tts      # about 18,700 characters, audio/ (not committed)
uv run python -m spoken_entities.pipeline asr      # 480 Scribe calls -> data/transcripts.jsonl
uv run python -m spoken_entities.pipeline extract  # 960 Claude calls -> data/extractions.jsonl
# the recogniser comparison: the same two steps per set-up (also with --asr scribe_v2)
uv run python -m spoken_entities.pipeline asr --asr scribe_v2_keyterms
uv run python -m spoken_entities.pipeline extract --asr scribe_v2_keyterms
```

Every stage is cached and appends only what is missing. Transcripts and Claude extractions are
committed; the rules extractor runs at scoring time, so CI checks the current code against the
cached transcripts.

## License

MIT
