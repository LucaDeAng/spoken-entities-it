# spoken-entities-it

**When an Italian voice agent mishears a customer code, an IBAN or a meter reading, does it notice?**

A voice agent on an Italian utility line has to catch values read aloud: customer codes, delegation
codes, birth dates, meter readings, amounts, POD codes, IBANs, fiscal codes. A misheard value that
fails a check is cheap: the agent asks again. A misheard value that passes is the expensive one,
because the agent acts on it: the wrong account is looked up, the wrong reading is billed. This repo measures
that second case, which I call **silent wrong**, through a real speech pipeline.

## Setup

```
32 synthetic values × 2 ways of saying them × 2 voices × 3 channels = 384 recordings
text ─► ElevenLabs TTS ─► channel ─► ElevenLabs Scribe ─► extractor ─► validator ─► outcome
```

- **Values.** Eight entity types for Brezzaluce Energia, the fictional utility of
  [deployment-in-a-box](https://github.com/LucaDeAng/deployment-in-a-box), four values each, none
  assignable to anyone: fiscal codes use the place code `Y999`, IBANs bank and branch `99999`, PODs
  distributor `999` ([`entities.py`](src/spoken_entities/entities.py)). That choice turned out to
  matter (see Results).
- **Ways of saying them.** *natural* is one common way to say it: "ci, sessantatré, zero, cinque";
  "centottanta euro e cinquantanove centesimi". *spelled* is digit by digit, with letters in the
  city alphabet: "D come Domodossola".
- **Voices.** An ElevenLabs default voice (English-native) speaking Italian, and a native Italian
  voice from the public library, both on `eleven_flash_v2_5`. They play the caller.
- **Channels.** The clean TTS file; a phone line (8 kHz, 300–3400 Hz, G.711 μ-law, via ffmpeg); the
  same line with one mild level of pink noise.
- **Recognition.** ElevenLabs Scribe (`scribe_v1`, batch, Italian, no keyterms).
- **Extractors.** A deterministic rules normaliser ([`italian.py`](src/spoken_entities/italian.py)) and
  Claude Haiku 5.5 and Opus 5.5 with structured output, which may return null or mark a value unsure.
- **Validators.** IBAN mod-97 and the fiscal-code check letter are real checksums. The other six types
  only have a format check.
- **Outcomes.**
  - **correct:** the value is right and the extractor is sure of it;
  - **re-ask:** no value, marked unsure (even when right), or rejected by the validator, so the agent asks again;
  - **silent wrong:** a wrong value that passes the validator and is not marked unsure, so the agent acts on it.

## Results

Full tables, and every wrong value with what caught it: [docs/results.md](docs/results.md). Each
extractor saw 384 recordings.

| extractor | right first time | re-ask: right but unsure | re-ask: other | silent wrong |
|---|---|---|---|---|
| rules | 87% | 0% | 13% | 0 |
| Claude Haiku 5.5 | 75% | 5% | 20% | 0 |
| Claude Opus 5.5 | 78% | 9% | 13% | 0 |

0 of 384 is 128 distinct recordings through three channels that mostly agree, so the 95% upper
bound is about 3%, not 1%.

- **No wrong value got through, for different reasons.** Almost every error fell on the two long
  codes, and mostly on two quirks of my unassignable values: the run of ten nines in every IBAN came
  back with nines missing or one extra, and the `Y` of place code `Y999` came back as "X" or "I".
  Depending on type and extractor, 33–62% of IBANs and fiscal codes were not captured correctly.
  IBANs mostly produced no valid value at all; fiscal codes mostly came back with the wrong letter.
  For the rules normaliser the checksum did the work: it turned all 20 wrong values into re-asks.
  For Claude it barely mattered: Claude marked 12 of 13 (Haiku) and 8 of 8 (Opus) of its wrong
  values unsure itself.
- **Without the checksum, the rules normaliser would have acted on 20 of 96 IBANs and fiscal codes**
  (21%; 95% CI 14–30% if the recordings were independent, 9–33% resampling each value's voices and
  channels together). The 20 come from 8 clips, 19 were spelled, and 19 sit on the `Y` or the nines.
  Claude would have acted on 1 (Haiku) and 0 (Opus). The lesson: a checksum or a read-back on every
  code that can carry one, because a format check stands in for neither.
- **Opus's caution costs turns, and the checksum can buy them back.** Opus marked 43 of 48 fiscal
  codes unsure, 26 of them right. A policy where a value that passes the checksum is accepted even
  if marked unsure takes Opus from 78% to 86% right first time (Haiku from 75% to 78%) and lets no
  wrong value through. The extractor's doubt and the validator overlap; design them together.
- **Haiku is cautious where it shouldn't be.** It got 17 of 48 delegation codes right and was sure
  of 11, where rules and Opus got 46. On "di LGK3DE" it returned nothing instead of reading "di" as D.
- **Asking the caller to spell works.** Of the 23 natural IBANs the rules normaliser missed, the
  spelled version of the same value came through right in 18.
- **The phone line barely mattered here.** Clean to noisy phone moved right-first-time by at most
  about three points for any extractor. Synthetic voices are clear and steady, the noise was mild,
  and a real caller is neither.

## How this relates to τ-Entity

Sierra's [τ-Entity](https://sierra.ai/blog/tau-entity-can-voice-agents-get-the-details-right)
([paper](https://arxiv.org/abs/2609.13602)) tests full voice agents end to end on capturing,
verifying and repairing entities over a call, in several languages; Italian is not among them. This
repo is narrower: one Italian utility's entity types, one pass through recognition and extraction,
and what the validator does with the result. It does not measure repair over turns.

## Limits

- **My test values make the long codes harder than real ones.** Every IBAN carries ten nines in a
  row and every fiscal code the place code `Y999`; real place codes start with A–M or Z. The checksum
  mechanism is real; these error rates are not a forecast.
- **Synthesis and recognition errors are not separated.** "Y come ipsilon" is not a city-alphabet
  spelling, and a transcript reading "I come ipsilon" suggests the TTS read Y as "i". I have not
  listened to every failing clip or run a second recogniser.
- **Synthetic speech only.** Two TTS voices, no accents, no hesitation, no self-correction ("no
  scusi, sette"). The pipeline is ready for recorded human speech; the numbers above are not a
  forecast for it.
- **Small, correlated cells.** Each type has 16 distinct recordings (8 texts × 2 voices), and the
  three channels gave the same outcome for most of them. A 0 in one type means under about 1 in 5.
  The Wilson intervals in docs/results.md assume independence and are too narrow.
- **The rules extractor was fixed after I read these transcripts.** It did not rejoin number words
  that Scribe split ("cinquantasette mila novecento trentuno"), read "3D come Domodossola" as two D's,
  and read "doppia vu" as V. With those bugs it let two wrong values through. There is no held-out
  set, so its 0 and its 87% are optimistic. The Claude prompt was written once and not changed.
- **One recogniser, one run, batch.** Scribe v1 without keyterms, not the streaming recogniser a
  live agent uses; each Claude extraction ran once at `effort: low`.
- **Amounts, dates and readings have no checksum**, so for them a misheard value that keeps its
  format can only be caught by reading it back to the caller. In this set every one was recovered.

## Next

- Values with realistic digit and letter patterns (a non-Y place code, no run of nines), and the
  failing clips committed so they can be heard.
- Scribe v2 Realtime with the spelling-alphabet words as
  [keyterms](https://elevenlabs.io/blog/introducing-scribe-v2), and a second recogniser.
- Harder channels (lower SNR, a narrowband mobile codec) and consented human recordings.
- Repair, not just re-ask: re-asking the same audio repeats the same error, so switch how the
  caller gives the value (spelled, keypad) and measure how often the second try lands.

## Run it

```bash
uv sync
uv run pytest -q                                  # no keys needed
uv run python -m spoken_entities.score            # rebuild docs/results.md from data/, no keys
```

Regenerating the data needs `ELEVENLABS_API_KEY` and `ANTHROPIC_API_KEY` (environment, or
`~/.secrets/{elevenlabs,anthropic}.env`):

```bash
uv run python -m spoken_entities.pipeline tts      # 13,100 characters, audio/ (not committed)
uv run python -m spoken_entities.pipeline asr      # 384 Scribe calls -> data/transcripts.jsonl
uv run python -m spoken_entities.pipeline extract  # 768 Claude calls -> data/extractions.jsonl
```

Every stage is cached and appends only what is missing. Transcripts and Claude extractions are
committed; the rules extractor runs at scoring time, so CI checks the current code against the
cached transcripts.

## License

MIT
