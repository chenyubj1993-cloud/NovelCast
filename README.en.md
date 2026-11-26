# NovelCast

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE) · ![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)

NovelCast turns a novel into a multi-voice audiobook. An LLM reads the book in blocks and casts every line to a character as `{character, text, emotion}`, a book-wide roster keeps each character on one voice from chapter 1 to the end, and local **IndexTTS-2.5** renders each line with its own emotion before merging the lines into chapter files. Annotation, LLM responses and per-line audio are all cached on disk, so an interrupted run resumes instead of starting over. The name is Novel + Cast — the dramatis personae.

## How it works

1. **Stage 0 · Character roster** — the whole book is read in slices and reduced to `characters.json` (name, aliases, gender, age, role); the roster constrains later annotation, so one person does not split into two characters when the text switches from a name to a nickname.
2. **Stage 1 · Script annotation** — blocks are annotated concurrently into `{character, text, emotion}`, each chunk carrying the roster in its prompt.
3. **Casting** — `cast.json` assigns one voice per character for the whole book: fixed narrator, same-gender voices kept apart, aliases of one person sharing one voice.
4. **Stage 2 · TTS** — lines are synthesized and merged per chapter; existing chapters and segments are skipped, so re-running the same command is safe.

## Features

- **Consistent cast across the whole book** — a `characters.json` roster plus a `cast.json` voice table, instead of per-chapter guessing.
- **Line-level resume** — `segments.json` beside `seg_0000.wav`… stores a `sha1(text + character + emotion)` fingerprint per line; only matching lines whose audio still opens are reused, everything else is re-rendered. WAVs go to `.part` and are `os.replace`d, so a hard kill leaves no half files.
- **40-character line splitting** — longer lines are split losslessly on sentence punctuation (then commas, then a hard cut) to stay under IndexTTS's internal low-VRAM splitting on 8 GB GPUs, which otherwise inserts a mysterious 200 ms pause mid-sentence.
- **Loudness normalization** — each chapter is normalized to `loudness_lufs` (−18 LUFS by default) with peaks capped, and gaps between consecutive dialogue lines are shorter than after narration.
- **Per-line emotion** — text mode turns each `emotion` tag into a Chinese delivery prompt (e.g. “有些不悦，语气稍沉”) with deliberately narrow speed changes; alternatively an 8-dimension emotion vector, or off entirely.
- **Input formats** — `.epub` (spine order), `.txt` (UTF-8 / GBK / GB2312 / UTF-16), `.docx`, `.doc`.
- **Voice bank** — build real-speaker references from open corpora; secondary characters and crowd lines draw from it while the narrator and leads keep stable synthetic voices.
- **Dry run, chapter selection, offline replay** — `--dry-run` prints the plan, `--chapters`/`-n` pick chapters, `--offline` re-renders existing scripts with no LLM call.

## Install

Requires **Python 3.11–3.12**.

```bash
git clone https://github.com/<you>/NovelCast.git
cd NovelCast
pip install -e ".[dev]"
```

- **No FFmpeg required.** Audio is decoded, resampled and concatenated in-process with `soundfile` and `soxr`; nothing shells out to `ffmpeg`.
- The base install is pure Python and light: `torch` and the IndexTTS runtime are **not** pulled in. Install them yourself for local synthesis.
- **Model weights are not in the repo.** Put IndexTTS-2.5 (~5.1 GB) into `models/IndexTTS-2.5`:

```bash
modelscope download --model IndexTeam/IndexTTS-2.5 --local_dir models/IndexTTS-2.5
# or: huggingface-cli download IndexTeam/IndexTTS-2.5 --local-dir models/IndexTTS-2.5
```

Expected files include `gpt.pth`, `s2mel.pth`, `codec.pth`, `config.yaml` and the `qwen0.6bemo4-merge/` emotion encoder. The weights are licensed separately from this repo — check the model card before commercial use.

Local synthesis also needs the IndexTTS source tree and a CUDA build of PyTorch:

```bash
git clone https://github.com/index-tts/index-tts third_party/index-tts
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128   # RTX 50 / Blackwell
pip install transformers==4.52.1 tokenizers==0.21.0 accelerate librosa \
            numba==0.63.0 llvmlite==0.46.0 soundfile soxr descript-audiotools \
            modelscope jieba cn2an omegaconf
```

No GPU? Use `--tts edge` (free, online) — the whole pipeline works without any local model.

## Quick start

```bash
novelcast doctor                        # Python, key deps, CUDA, model dir, provider
novelcast run book.epub -n 2 --tts edge # dependency-free smoke test: no local models, no GPU
novelcast run book.epub --dry-run       # print the plan, call nothing
novelcast run book.epub -n 2            # full local run, first two chapters
novelcast run book.epub -o out/my-book  # output somewhere other than output/<book>_有声书/
```

Configuration is read from `config/settings.json` (create it from the example). The global `--config` flag goes **before** the subcommand: `novelcast --config my.json run book.epub`.

### CLI reference

| Command / flag | Meaning |
|---|---|
| `novelcast run <file>` | Document → audio |
| `novelcast doctor` / `novelcast config` | Check the environment / print merged config |
| `-o, --output` | Output directory (default `output/<book>_有声书`) |
| `-n, --first-chapters N` | First N chapters only |
| `--chapters 1,3,5-7` | Explicit chapter numbers |
| `--first-chars N` | First N characters of each chapter (preview) |
| `--tts {indextts2,edge,openai}` | TTS engine |
| `--format {wav,m4b}` | per-chapter WAV, or one M4B with chapter marks (needs ffmpeg) |
| `--model-version {2,2.5}` | IndexTTS version |
| `--speed 0.5–2.0` | Speed multiplier, smaller is faster (`duration_factor`) |
| `--emotion-mode {text,vector,off}` | How emotion drives delivery |
| `--dry-run` / `--split-only` | Plan only / annotate only |
| `--offline` | Reuse existing scripts, never call the LLM |
| `--fresh` / `--restart` | Wipe everything / keep scripts, re-render audio |
| `--keep-segments` | Keep `_temp_XXX/` caches (deleted after a successful chapter otherwise) |
| `--rebuild-roster` / `--rebuild-cast` | Re-extract `characters.json` / rebuild `cast.json` |

## Cloud TTS (OpenAI-compatible)

No GPU? Point synthesis at any service that implements `POST /v1/audio/speech` (OpenAI, SiliconFlow's CosyVoice, one-api / new-api gateways):

```json
"tts": {
  "provider": "openai",
  "cloud_base_url": "https://api.openai.com/v1",
  "cloud_api_key": "sk-...",
  "cloud_model": "gpt-4o-mini-tts",
  "cloud_voices": {"female": ["nova"], "male": ["onyx"], "unknown": ["alloy"]}
}
```

`OPENAI_BASE_URL` / `OPENAI_API_KEY` are used when the config fields are empty. Then:

```bash
novelcast run input/book.epub -n 2 --tts openai
```

- `cloud_voices` holds **provider voice ids**, not local files; `character_voices` overrides must be cloud ids too.
- Emotion is passed as `instructions` (supported by `gpt-4o-mini-tts`; other services ignore it).
- The response must be WAV (`cloud_format` is configurable, but concatenation needs WAV).
- Billing is per character — try `--chapters 1 --first-chars 500` first.

## Configuration

Start from [`config/settings.example.json`](config/settings.example.json), copy it to `config/settings.json`, and keep the real file out of git. `novelcast config` prints the merged result.

| Key | Meaning | Default |
|---|---|---|
| `roster_mode` | `full` pre-scans the whole book for characters; `off` skips it | `full` |
| `tts.max_segment_chars` | max chars per TTS segment; `null` = auto (40 local, 120 edge/cloud) | `null` |
| `tts.cloud_concurrency` | parallel requests for edge/cloud TTS | `4` |
| `tts.provider` | `mimoai` (cloud), `indextts2` or `edge` | `mimoai` in code; the example file ships `indextts2` |
| `tts.model_version` | `"2"` or `"2.5"`; 2.5 enables `<字\|拼音>` annotations and duration control | `"2"` |
| `tts.duration_factor` | 0.5–2.0, smaller is faster | `1.0` |
| `tts.emotion_mode` | `text`, `vector` or `off` | `text` |
| `tts.emo_alpha` | Emotion strength, 0–1 (1.0 is loudest and tiring) | `0.55` |
| `tts.loudness_lufs` | Chapter loudness target | `-18.0` |
| `tts.silence_narration` / `silence_dialogue` | Gap after narration / between dialogue lines | `0.4` / `0.15` |
| `generation.chunk_size` | Characters per annotation block | `1500` |
| `concurrency.llm_concurrency` / `tts_concurrency` | Segments per block / TTS requests in flight | `3` / `5` |
| `voice_presets`, `character_voices` | Voice name → engine voice; per-character overrides | — |
| `voice_bank` | Path to a `voice_bank.json` built from open corpora | `output/_refs/voice_bank.json` |

Emotion labels are per line. `text` mode maps them to prompts and applies modest speed shifts (angry 0.95×, sad 1.06×); `vector` uses 8 dimensions (happy/angry/sad/afraid/disgusted/melancholic/surprised/calm). Neutral is not passed through.

## Output layout

```
output/<book>_有声书/
├── characters.json                 # roster: name / aliases / gender / age / role / appearances
├── cast.json                       # character → voice, plus the narrator voice
├── 001_Chapter Title_script.json   # lines[] = {character, text, emotion, voice}
├── 001_Chapter Title.wav           # final audio
├── 001_Chapter Title_part02.wav    # when a chapter exceeds max_duration_per_file
└── _temp_001/segments.json         # per-line resume manifest (removed on success unless --keep-segments)

llm_raw_responses/<book>/<chapter>/  # raw LLM responses + {timestamp}_*_readable.txt side-by-side check
```

The roster and cast are plain JSON: edit them and re-run without `--rebuild-roster` / `--rebuild-cast`.

## Voice bank (optional)

The eight built-in voices are edge-tts synthetic, so clones of them still sound synthetic. For natural voices, build a bank from open corpora and point `voice_bank` at it:

```bash
python scripts/fetch_aishell3_modelscope.py --per-speaker 4
python scripts/build_voice_bank.py data/aishell3_ms --count 24
python scripts/fetch_ws4tts.py --max-bytes 2000MB   # streams the tar.gz and stops when satisfied
python scripts/build_voice_bank.py data/ws4tts --count 28 --style broadcast \
    --source-name ws4tts --id-prefix WS --infer-gender --merge
```

This yields 24 kHz references (≤12 s, peak −6 dBFS) under `output/_refs/` plus `voice_bank.json` with speaker, gender, age, source and `style`. The cast manager keeps edge voices for the narrator and the top `main_character_count` (6) characters, prefers broadcast-style bank voices for secondary roles, and rotates crowd voices (`众人`/`路人`/unknown) by gender so a scene is not read by one person throughout.

## Tests

`ash
pip install -e .[dev]
pytest -q          # ~70+ unit tests, no network, no GPU
ruff check novelcast scripts tests
`

Enable the bundled pre-commit hook so a failing test blocks the commit:

`ash
git config core.hooksPath .githooks
`

## Limitations

- The roster covers only the chapters you selected: characters that first appear in a skipped chapter are unknown to it.
- The roster is a reference list, not a hard constraint — the LLM can still emit out-of-roster characters; they get a stable crowd voice and are listed in the log.
- Chinese dialogue with elided subjects can still be attributed to the wrong speaker. Annotate with `--split-only` and read `*_readable.txt` before spending hours on audio.
- IndexTTS runs **serially**, one line at a time: RTF ≈ 1.1–1.9 on an 8 GB laptop GPU, first load 1–2 minutes. Resume saves wasted work, not wall-clock per chapter.
- With `--model-version 2`, pronunciation annotations such as `<重|CHONG2>` are read aloud literally; they only exist in 2.5.
- `.mobi` is **not** supported by the reader — `.epub`, `.txt`, `.docx` and `.doc` only.

## Data and licenses

- **Code:** MIT, see [`LICENSE`](LICENSE).
- **AISHELL-3:** Apache-2.0, usable commercially.
- **WenetSpeech4TTS:** CC BY-NC 4.0 — **non-commercial only**. Swap in a licensed corpus (e.g. MagicData) for commercial audiobooks.
- **Emilia:** CC BY-NC 4.0; **WenetSpeech:** application-gated, non-commercial.
- **edge-tts:** talks to Microsoft's consumer endpoint, which is not a licensed production TTS API — treat generated audio accordingly.
- **IndexTTS-2.5 weights:** licensed by their authors, separate from this repo's MIT license.
- Real human references also involve voice rights — confirm permission before publishing audio made from them.
