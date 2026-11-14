---
name: voice-to-music
description: Turn a voice recording (ogg/opus/m4a/wav) into music — hum/sing → melody MIDI, add chords/beat/bass, process the vocal, and mix to WAV/MP3. Use when the user says "ovozni musiqaga aylantir", "make a song from my voice", "beat qo'sh", "melodiyani MIDI qil".
---

# Voice → Music (music_lab)

All tooling is local. Python env: `/Users/mcodevs/my_projects/music_lab/.venv` (Python 3.11).
Run scripts with `.venv/bin/python -I script.py` and keep work files in `work/`, finished tracks in `output/`.

## Installed tools
- **ffmpeg** — decode ogg/opus, resample, encode mp3.
- **librosa** — tempo/beat tracking, key (chroma), pitch (`librosa.pyin`), onset detection, time-stretch / pitch-shift.
- **basic-pitch** (Spotify, ONNX) — audio → MIDI note transcription (best for humming/singing a melody).
  Always pass the ONNX model explicitly: `predict(path, glob('.venv/lib/python3.11/site-packages/basic_pitch/saved_models/icassp_2022/*.onnx')[0])`
  (default path is CoreML and fails). Needs `setuptools<81` and `scikit-learn<=1.5.1` pinned — already installed.
- **pretty_midi** — build/edit MIDI: melody, chords, bass, drums.
- **fluidsynth** + General MIDI SoundFont `soundfonts/FluidR3_GM.sf2` — render MIDI → WAV:
  `fluidsynth -ni -q -g 0.8 -r 44100 -F out.wav soundfonts/FluidR3_GM.sf2 in.mid`
- **pedalboard** (Spotify) — vocal FX: HPF, compressor, EQ, reverb, delay, chorus, autotune-ish via pitch shift, limiter.
- **pyloudnorm** — master loudness to ~-14 LUFS.
- **Demucs 4.1** (Meta) — song/video → minus/instrumental + vocal stems via `scripts/separate_minus.py`:
  `.venv/bin/python -I scripts/separate_minus.py song.m4a --name "Song" --check-bleed`
  (handles Cyrillic filenames, ~30 s per 3-min song on MPS; models cached in `~/.cache/huggingface`).
  Pass `--four-stems` for 4 stems (drums/bass/other/vocals). `--check-bleed` verifies leftover vocal < −40 dB.

## Scripts toolkit (`scripts/`)
- `scripts/dsp.py` — shared DSP, voice diagnostics (`diagnose_voice`), cold/nasal cleanup, de-esser, Match-EQ, vocal chain, dry-first space bus (defaults: reverb `−18 dB`, room `0.5`, delay `−26 dB`), and `master_limiter`.
- `scripts/separate_minus.py` — Demucs `htdemucs_ft` stem separation + LUFS balance + `--check-bleed` + WAV/MP3 export.
- `scripts/voice_polish.py` — solo voice polish (default `−18 dB` reverb, `0.5` room, `−26 dB` delay, `−15 LUFS`), with `--diagnose` and `--fix-cold`.
- `scripts/voice_cold_fix.py` & `scripts/voice_denasal.py` — standalone cold/hoarse breathiness (`reduce_db=7`) and nasal resonance (`strength=0.7`) cleaners.
- `scripts/vocal_on_minus.py` & `scripts/phrase_timing.py` — a-cappella cover onto minus (`--project work/<name>`, `--config`, `--fix-cold`, `--suggest`, `--plot`).
- `scripts/clip_cover.py` — lip-synced music video cover from a-cappella video + lav mic onto minus (`--init clip.json`, `--fix-cold`).
- `scripts/video_optimize.py` — H.264 CRF 20 (30 fps CFR, bt709, `+faststart`) + 2-pass loudnorm (`−14 LUFS`), plus `--polish-voice` remux with `.mov` `start_time` offset (`adelay`) handling and xcorr lip-sync check.
- Diagnostics are **advisory only**: `--fix-cold suggested` when HNR (Praat-style autocorrelation) < 15 dB or LTAS resonance excess 500 Hz > 2.5 dB / 1.4 kHz > 3.5 dB. No script enables cold/nasal cleanup on its own — listen first, then pass `--fix-cold`.
- Pitch tracks are cached as `tmp/<name>_f0_<content-hash>.npy`; a different take, song or `--fix-cold` run never reuses a stale track. Safe to delete `tmp/` at any time.

## Step 1 — Listen first (analysis)
1. `ffmpeg -i in.ogg -ac 1 -ar 44100 work/voice.wav`
2. Decide what the recording IS — this decides the whole pipeline:
   - **Singing/humming a melody** → transcribe to MIDI (Step 2A).
   - **Speech / spoken words / rap** → keep the voice as the lead, build music under it (Step 2B).
   - **Beatbox/tapping** → onset detection → drum MIDI.
   Check with `librosa.pyin` voiced ratio + pitch stability; ask the user if unsure.
3. Estimate tempo (`librosa.beat.beat_track`) and key (mean chroma vs Krumhansl profiles).

## Step 2A — Melody to arrangement
- `basic_pitch.inference.predict(path)` → MIDI; clean it: drop notes < 80 ms, quantize to the 1/16 grid at the detected tempo, snap to the detected scale.
- Harmonize: one chord per bar chosen from diatonic triads that contain the bar's longest melody notes.
- Add bass (chord roots, octave 2), drums (GM channel 10: kick 36, snare 38, hat 42), pad/piano chords.
- Render with fluidsynth; optionally also lay the original vocal on top.

## Step 2B — Voice over music / Solo polish
- For solo voice memos: run `.venv/bin/python -I scripts/voice_polish.py in.m4a "Title"` (starts dry at `−18 dB` reverb, `0.5` room, `−26 dB` delay, `−15 LUFS`). Run with `--diagnose` first or add `--fix-cold` if hoarse/nasal.
- For voice over music: clean vocal (trim silences/long pauses, HPF 85 Hz, de-noise gently, compressor ratio 3–4, presence EQ +3 dB @ 3 kHz, dry-first reverb `−18 dB` / room `0.5`, delay `−26 dB`).
- Pick tempo (speech has none — choose by mood: lo-fi 80–90, pop 100–120, trap 140) and key; build chords/bass/drums with pretty_midi.
- Align phrases to bars (cut at silences, place each phrase on a downbeat), sidechain-duck music −4 dB under the voice.

## Step 2C — User's a-cappella cover onto a minus (`scripts/vocal_on_minus.py`)
- Separate original song with `scripts/separate_minus.py` and clean user's take with Demucs (`--two-stems vocals`) first.
- Run `.venv/bin/python -I scripts/vocal_on_minus.py --project work/<name> --out "Title"` (or pass `--voice`, `--orig-vocal`, `--minus`; add `--fix-cold` if congested).
- Alignment: phrase-level DTW (chroma CENS + voicing + onsets) of user vocal vs original vocal; the script auto-detects
  if the user skipped a long instrumental break. `--align global` (default) measured best; word-level DTW (`local`)
  and melody-based shift (`shift`) made timing WORSE on a real take — amateur singers phrase differently.
- Per phrase: Rubber Band `--pitchmap` pitch correction (75 %, vibrato kept, toward the original melody), then `-M` timemap stretch.
- Vocal chain: match-EQ toward original vocal tone (±6 dB, 60 %), STFT de-esser, comp 4:1 → EQ → comp 2:1, dry-first plate reverb `−18 dB` (room `0.5`), 3/16 delay `−26 dB`.
- Mix at original vocal/minus balance (+0.5 dB), 1.5 dB sidechain duck, master −12 LUFS / −1.2 dBFS.
  NOTE: pedalboard `Limiter` adds make-up gain — `dsp.master_limiter` iterates input gain to hit the LUFS target.
- Check with `scripts/phrase_timing.py --project work/<name> --plot` (writes `alignment_check.png`, measures onset + pitch-contour lag and break bleed).
- Timing fixes: `scripts/phrase_timing.py --project work/<name> --suggest` writes corrections to `phrase_shifts.json` ONLY where onset and
  pitch cues agree. Single-cue "lags" of 200–450 ms on an amateur take were measurement noise (the two cues contradicted each other).
  Best fixes come from the user's ears: add `{"from": "1:26.0", "to": "1:27.9", "shift_ms": 150}` (+ later / − earlier) and rerun.

## Step 2D — Lip-synced clip cover & video optimization
- **Music-video cover (`scripts/clip_cover.py`):** initialize `clip.json` with `--init work/<name>/clip.json --voice ... --orig-vocal ... --minus ... --video ...`, review `orig_onsets`/`minus_shift`, then run `.venv/bin/python -I scripts/clip_cover.py work/<name>/clip.json`.
- **Video + audio polish (`scripts/video_optimize.py`):** `.venv/bin/python -I scripts/video_optimize.py video.mov --polish-voice --verify-ssim` (exports `_optimized.mp4` + `_effects.mp4` and verifies `< 5 ms` lip-sync lag).

## Step 3 — Mix & master
- Sum stems in numpy, pedalboard `Limiter`, normalize to −14 LUFS with pyloudnorm, export WAV + `ffmpeg -b:a 320k` MP3 into `output/`.
- Always keep stems (`work/stems/*.wav`) and the `.mid` so the user can open them in a DAW.

## Rules
- Never overwrite the user's original recording.
- Render a short 20–30 s preview first, let the user pick genre/mood before the full track.
- Write the generating script into `scripts/` so the result is reproducible and tweakable.
