"""Hum / sing a melody -> full song (SKILL step 2A).

Pipeline:
  1. Transcribe the voice to notes (basic-pitch ONNX; pYIN fallback), monophonic clean-up.
  2. Beat grid that FOLLOWS the singer (beat tracking on the voice, or a fixed --bpm),
     downbeat phase picked from where the notes land, key by Krumhansl-Schmuckler.
  3. One chord per bar: diatonic triads scored on the bar's melody notes + a light
     progression prior (Viterbi), tonic forced on the last bar.
  4. Arrangement in pretty_midi: chords (piano/pad), bass on chord roots (octave 2),
     GM drums (kick 36, snare 38/side-stick 37, hat 42), an intro bar and a final chord.
  5. fluidsynth + soundfonts/FluidR3_GM.sf2 -> instrumental; the voice itself is kept
     (not quantized) with the usual dry vocal chain, ducked mix, mastered to -14 LUFS.

Usage:
  .venv/bin/python -I scripts/melody_to_song.py hum.m4a "My Song"
  .venv/bin/python -I scripts/melody_to_song.py hum.m4a "My Song" --style ballad --bpm 84 --key Am
  .venv/bin/python -I scripts/melody_to_song.py hum.m4a "My Song" --no-vocal --lead-program 73
Outputs (output/ unless the name contains a folder): <name>.wav/.mp3, <name> (minus).wav/.mp3
(only with the vocal), <name>.mid (arrangement), <name> (melody).mid (quantized, in-scale melody).
"""
import argparse
import glob
import os
import shutil
import subprocess
import sys
import tempfile
import numpy as np
import soundfile as sf
import librosa
import pretty_midi
import pyloudnorm as pyln
import scipy.signal as ss
from scipy.ndimage import median_filter
from pedalboard import Pedalboard, Compressor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dsp

SR = 44100
SOUNDFONT = os.path.join(ROOT, 'soundfonts', 'FluidR3_GM.sf2')
NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
FLAT_ALIASES = {'Db': 'C#', 'Eb': 'D#', 'Gb': 'F#', 'Ab': 'G#', 'Bb': 'A#'}
KK_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
KK_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
SCALES = {'major': [0, 2, 4, 5, 7, 9, 11], 'minor': [0, 2, 3, 5, 7, 8, 10]}
# (label, root offset from tonic, quality, prior); diminished triads are left out
CHORDS = {
    'major': [('I', 0, 'maj', 0.30), ('ii', 2, 'min', 0.05), ('iii', 4, 'min', 0.0),
              ('IV', 5, 'maj', 0.20), ('V', 7, 'maj', 0.25), ('vi', 9, 'min', 0.15)],
    'minor': [('i', 0, 'min', 0.30), ('III', 3, 'maj', 0.10), ('iv', 5, 'min', 0.20),
              ('v', 7, 'min', 0.0), ('V', 7, 'maj', 0.20), ('VI', 8, 'maj', 0.15), ('VII', 10, 'maj', 0.10)],
}
GOOD_MOVES = {('V', 'I'): 0.15, ('V', 'i'): 0.15, ('IV', 'V'): 0.10, ('iv', 'V'): 0.10,
              ('ii', 'V'): 0.10, ('IV', 'I'): 0.05, ('iv', 'i'): 0.05, ('vi', 'IV'): 0.05, ('VI', 'VII'): 0.05}
STYLES = {
    # chord_prog: GM program for the chord instrument; pad: sustained pad (None = off)
    'pop': dict(chord_prog=0, pad=48, bass_prog=33),
    'ballad': dict(chord_prog=0, pad=48, bass_prog=32),
}


# ---------------------------------------------------------------- transcription
def transcribe_basic_pitch(wav_path):
    from basic_pitch.inference import predict  # imported lazily: heavy, and optional
    import basic_pitch
    onnx = glob.glob(os.path.join(os.path.dirname(basic_pitch.__file__), 'saved_models', 'icassp_2022', '*.onnx'))
    if not onnx:
        raise RuntimeError('basic-pitch ONNX model not found')
    # the default CoreML model does not load here (references/music-toolkit.md)
    _, _, events = predict(wav_path, model_or_model_path=onnx[0], onset_threshold=0.5,
                           frame_threshold=0.3, minimum_note_length=80, minimum_frequency=65,
                           maximum_frequency=1100, melodia_trick=True)
    return [(float(s), float(e), int(p), float(a)) for s, e, p, a, *_ in events]


def transcribe_pyin(y, sr):
    """Fallback: notes from a median-filtered pYIN track (stable rounded-pitch runs >= 80 ms)."""
    hop = 256
    ya = librosa.resample(y, orig_sr=sr, target_sr=22050)
    midi = dsp.f0_pyin(ya, sr=22050, fmin=65, fmax=1000, hop_length=hop)
    voiced = ~np.isnan(midi)
    sm = np.where(voiced, median_filter(np.nan_to_num(midi), size=7), np.nan)
    r = np.where(voiced, np.round(sm), -1)
    notes, i = [], 0
    dt = hop / 22050
    while i < len(r):
        j = i
        while j + 1 < len(r) and r[j + 1] == r[i]:
            j += 1
        if r[i] >= 0 and (j - i + 1) * dt >= 0.08:
            notes.append((i * dt, (j + 1) * dt, int(r[i]), 0.8))
        i = j + 1
    return notes


def clean_notes(events, min_len=0.08):
    """Monophonic melody from (start, end, pitch, amp): drop short/weak notes, resolve overlaps by
    strength, fix isolated octave jumps (harmonic/sub-harmonic confusions)."""
    ev = [e for e in events if e[1] - e[0] >= min_len]
    if not ev:
        return []
    amps = np.array([e[3] for e in ev])
    amp_floor, amp_med = 0.25 * amps.max(), float(np.median(amps))
    # short AND clearly weaker than the typical note = breath/noise/click, not melody
    ev = sorted([e for e in ev if e[3] >= amp_floor and (e[1] - e[0] >= 0.25 or e[3] >= 0.6 * amp_med)],
                key=lambda e: e[0])
    if not ev:
        return []
    mono = []
    for s, e, p, a in ev:
        if mono and s < mono[-1][1]:
            ps, pe, pp, pa = mono[-1]
            if a * (e - s) > pa * (pe - ps):
                if s - ps >= min_len:
                    mono[-1] = (ps, s, pp, pa)
                else:
                    mono.pop()
                mono.append((s, e, p, a))
            elif e - pe >= min_len:
                mono.append((pe, e, p, a))
            continue
        mono.append((s, e, p, a))
    pitches = np.array([n[2] for n in mono], float)
    for i in range(len(mono)):
        ctx = np.r_[pitches[max(0, i - 3):i], pitches[i + 1:i + 4]]
        if len(ctx) >= 2:
            med = np.median(ctx)
            for k in (-12, 12):
                if abs(pitches[i] - med) > 9 and abs(pitches[i] + k - med) <= 5:
                    pitches[i] += k
                    break
    return [(s, e, int(p), a) for (s, e, _, a), p in zip(mono, pitches)]


# ---------------------------------------------------------------- key, grid, harmony
def parse_key(text):
    t = text.strip()
    mode = 'minor' if t.endswith('m') and not t.endswith('maj') else 'major'
    name = t[:-1] if mode == 'minor' else t.replace('maj', '')
    name = FLAT_ALIASES.get(name, name)
    if name not in NOTE_NAMES:
        raise ValueError(f'unknown key {text!r} (use e.g. C, F#, Bb, Am, C#m)')
    return NOTE_NAMES.index(name), mode


def detect_key(notes):
    hist = np.zeros(12)
    for s, e, p, _ in notes:
        hist[p % 12] += e - s
    best = (-np.inf, 0, 'major')
    for tonic in range(12):
        for mode, prof in (('major', KK_MAJOR), ('minor', KK_MINOR)):
            r = np.corrcoef(hist, np.roll(prof, tonic))[0, 1]
            if r > best[0]:
                best = (r, tonic, mode)
    return best[1], best[2], float(best[0])


def beat_grid(y, sr, notes, bpm=None):
    """Beat times (s) covering the melody. Auto mode tracks the singer's own (drifting) pulse."""
    first, last = notes[0][0], notes[-1][1]
    if bpm:
        period = 60.0 / bpm
        beats = first + period * np.arange(-8, int((last - first) / period) + 10)
        return beats, float(bpm)
    hop = 512
    env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
    tempo = float(np.atleast_1d(librosa.feature.tempo(onset_envelope=env, sr=sr, hop_length=hop,
                                                      start_bpm=100))[0])
    while tempo > 140:
        tempo /= 2
    while tempo < 70:
        tempo *= 2
    _, bf = librosa.beat.beat_track(onset_envelope=env, sr=sr, hop_length=hop, bpm=tempo, tightness=300)
    bt = librosa.frames_to_time(bf, sr=sr, hop_length=hop)
    period = 60.0 / tempo
    if len(bt) < 4:
        bt = first + period * np.arange(0, int((last - first) / period) + 2)
    else:
        period = float(np.median(np.diff(bt)))
    pre = bt[0] - period * np.arange(8, 0, -1)
    post = bt[-1] + period * np.arange(1, int(max(0.0, last - bt[-1]) / period) + 10)
    return np.r_[pre, bt, post], 60.0 / period


def pick_downbeat(beats, notes):
    """Bar phase (0-3) whose beat 1 gets the most note starts (duration-weighted)."""
    score = np.zeros(4)
    for s, e, _, _ in notes:
        i = int(np.argmin(np.abs(beats - s)))
        if abs(beats[i] - s) < 0.15:
            score[i % 4] += (e - s) * (1.5 if e - s > 0.3 else 1.0)
    return int(np.argmax(score))


def triad(tonic, root_off, quality):
    r = (tonic + root_off) % 12
    return [r, (r + (4 if quality == 'maj' else 3)) % 12, (r + 7) % 12]


def harmonize(notes, bars, tonic, mode):
    """One chord per bar via Viterbi over diatonic triads."""
    cands = CHORDS[mode]
    scale = {(tonic + d) % 12 for d in SCALES[mode]}
    n_bars, n_c = len(bars), len(cands)
    emit = np.zeros((n_bars, n_c))
    for b, (b0, b1) in enumerate(bars):
        w_tot = 0.0
        fit = np.zeros(n_c)
        for s, e, p, _ in notes:
            ov = min(e, b1) - max(s, b0)
            if ov <= 0:
                continue
            w = ov * (1.5 if abs(s - b0) < 0.12 or abs(s - (b0 + b1) / 2) < 0.12 else 1.0)
            w_tot += w
            for c, (_, ro, q, _) in enumerate(cands):
                fit[c] += w * (1.0 if p % 12 in triad(tonic, ro, q) else (-0.2 if p % 12 in scale else 0.0))
        emit[b] = (fit / w_tot if w_tot > 0 else 0.0) + np.array([c[3] for c in cands])
    emit[-1, 0] += 1.0  # end on the tonic
    score = emit[0].copy()
    back = np.zeros((n_bars, n_c), int)
    for b in range(1, n_bars):
        trans = np.array([[GOOD_MOVES.get((cands[i][0], cands[j][0]), 0.0) for j in range(n_c)]
                          for i in range(n_c)])
        tot = score[:, None] + trans
        back[b] = np.argmax(tot, axis=0)
        score = tot[back[b], np.arange(n_c)] + emit[b]
    path = [int(np.argmax(score))]
    for b in range(n_bars - 1, 0, -1):
        path.append(back[b][path[-1]])
    return [cands[c] for c in path[::-1]]


def snap(t, grid):
    return float(grid[int(np.argmin(np.abs(grid - t)))])


# ---------------------------------------------------------------- arrangement
def build_midi(notes, bars, chords, tonic, style, bpm, lead_program, rng):
    st = STYLES[style]
    pm = pretty_midi.PrettyMIDI(initial_tempo=bpm)
    chord_i = pretty_midi.Instrument(program=st['chord_prog'], name='chords')
    pad_i = pretty_midi.Instrument(program=st['pad'], name='pad')
    bass_i = pretty_midi.Instrument(program=st['bass_prog'], name='bass')
    drums = pretty_midi.Instrument(program=0, is_drum=True, name='drums')

    def add(inst, pitch, t0, t1, vel):
        v = int(np.clip(vel + rng.integers(-6, 7), 1, 127))
        inst.notes.append(pretty_midi.Note(velocity=v, pitch=int(pitch), start=float(t0), end=float(max(t1, t0 + 0.05))))

    prev = None
    for bi, ((b0, b1), (label, ro, q, _)) in enumerate(zip(bars, chords)):
        beat = (b1 - b0) / 4
        pcs = triad(tonic, ro, q)
        # voice-led close triad around C4-G4
        options = []
        for inv in range(3):
            v = sorted(60 + ((pcs[(k + inv) % 3] - 0) % 12) for k in range(3))
            v = [x if x >= v[0] else x + 12 for x in v]
            options.append(sorted(v))
        voicing = min(options, key=lambda v: 0 if prev is None else sum(abs(a - b) for a, b in zip(v, prev)))
        prev = voicing
        root = 36 + (pcs[0] - 36) % 12  # C2..B2
        intro, outro = bi == 0, bi == len(bars) - 1
        if style == 'pop':
            hits = [(0, 1.5), (1.5, 1.0), (2.5, 1.5)] if not outro else [(0, 4)]
            for off, dur in hits:
                for pch in voicing:
                    add(chord_i, pch, b0 + off * beat, b0 + (off + dur) * beat, 72)
        else:  # ballad: 8th-note arpeggio
            arp = [voicing[0] - 12, voicing[2] - 12, voicing[1], voicing[2], voicing[0] + 12, voicing[2], voicing[1], voicing[2] - 12]
            for k, pch in enumerate(arp if not outro else arp[:1]):
                add(chord_i, pch, b0 + k * beat / 2, b0 + (k + 1) * beat / 2 + (3 * beat if outro else 0), 64)
        for pch in voicing:
            add(pad_i, pch - 12, b0, b1, 46)
        if style == 'pop' and not outro:
            for off, pch in [(0, root), (1.5, root), (2, root + 7 if root + 7 <= 50 else root - 5), (3, root)]:
                add(bass_i, pch, b0 + off * beat, b0 + (off + 0.9) * beat, 88)
        else:
            for off in ([0, 2] if not outro else [0]):
                add(bass_i, root, b0 + off * beat, b0 + (off + (1.9 if not outro else 4)) * beat, 84)
        if intro:
            continue  # intro bar: no drums
        if outro:
            add(drums, 49, b0, b0 + beat, 100)
            add(drums, 36, b0, b0 + beat / 2, 100)
            continue
        if style == 'pop':
            for off in (0, 2, 2.5):
                add(drums, 36, b0 + off * beat, b0 + (off + 0.25) * beat, 96)
            for off in (1, 3):
                add(drums, 38, b0 + off * beat, b0 + (off + 0.25) * beat, 90)
            for k in range(8):
                add(drums, 42, b0 + k * beat / 2, b0 + (k + 0.4) * beat / 2, 70 if k % 2 == 0 else 50)
        else:
            add(drums, 36, b0, b0 + beat / 4, 84)
            add(drums, 37, b0 + 2 * beat, b0 + 2.25 * beat, 70)
            for k in range(4):
                add(drums, 42, b0 + k * beat, b0 + (k + 0.4) * beat, 45)
        if bi == 1:
            add(drums, 49, b0, b0 + beat, 90)  # crash where the song proper starts
    pm.instruments += [chord_i, pad_i, bass_i, drums]

    melody = pretty_midi.Instrument(program=lead_program if lead_program is not None else 0, name='melody')
    for s, e, p, _ in notes:
        add(melody, p, s, e, 90)
    return pm, melody


def render(pm, wav_path):
    if not os.path.exists(SOUNDFONT):
        sys.exit(f'SoundFont missing: {SOUNDFONT}\nGet it once with: sh scripts/get_soundfont.sh '
                 f'(~120 MB download, see soundfonts/README.md)')
    if shutil.which('fluidsynth') is None:
        sys.exit('fluidsynth not found: brew install fluid-synth')
    with tempfile.TemporaryDirectory() as td:
        mid = os.path.join(td, 'arr.mid')
        pm.write(mid)
        subprocess.run(['fluidsynth', '-ni', '-q', '-g', '0.6', '-r', str(SR), '-F', wav_path, SOUNDFONT, mid],
                       check=True, capture_output=True)
    y, sr = sf.read(wav_path, always_2d=True)
    if sr != SR:
        y = np.column_stack([librosa.resample(y[:, c], orig_sr=sr, target_sr=SR) for c in range(y.shape[1])])
    return y.T.astype(np.float32)


def trim_tail(x, keep=1.0, floor_db=-60.0):
    """Drop trailing silence from a (2, N) signal, keeping `keep` s after the last audible sample."""
    loud = np.flatnonzero(np.abs(x).max(0) > 10 ** (floor_db / 20))
    return x[:, :min(x.shape[1], loud[-1] + int(keep * SR))] if len(loud) else x


# ---------------------------------------------------------------- main
def main():
    p = argparse.ArgumentParser(description='Turn a hummed/sung melody into an arranged song.')
    p.add_argument('src', help='Voice recording (wav, m4a, ogg, mp3, ...)')
    p.add_argument('name', help='Output name (written to output/<name>.* unless it contains a folder)')
    p.add_argument('--style', choices=sorted(STYLES), default='pop', help='Arrangement style (default: pop)')
    p.add_argument('--bpm', type=float, default=None, help='Fixed tempo; default: follow the singer')
    p.add_argument('--key', default=None, help='Force key, e.g. C, F#, Bb, Am (default: detected)')
    p.add_argument('--transcriber', choices=['basic-pitch', 'pyin'], default='basic-pitch')
    p.add_argument('--no-vocal', action='store_true', help='Instrumental only: the melody is played by --lead-program')
    p.add_argument('--lead-program', type=int, default=None,
                   help='GM program for the melody (default: off with vocal, 73 flute with --no-vocal)')
    p.add_argument('--intro-bars', type=int, default=1, help='Accompaniment-only bars before the voice (default: 1)')
    p.add_argument('--vocal-db', type=float, default=2.0, help='Vocal level over the music in LU (default: +2)')
    p.add_argument('--lufs', type=float, default=-14.0, help='Target loudness (default: -14)')
    p.add_argument('--reverb-db', type=float, default=dsp.DEFAULT_REVERB_DB)
    p.add_argument('--room', type=float, default=dsp.DEFAULT_ROOM)
    p.add_argument('--fix-cold', action='store_true', help='Cold/nasal cleanup on the voice first')
    p.add_argument('--seed', type=int, default=0, help='Velocity humanization seed')
    args = p.parse_args()

    src = os.path.abspath(args.src)
    if not os.path.exists(src):
        sys.exit(f'Input not found: {src}')
    out_base = os.path.abspath(args.name) if os.path.dirname(args.name) else os.path.join(ROOT, 'output', args.name)
    os.makedirs(os.path.dirname(out_base), exist_ok=True)
    lead_program = args.lead_program if args.lead_program is not None else (73 if args.no_vocal else None)
    rng = np.random.default_rng(args.seed)

    voice = dsp.load_mono(src, sr=SR)
    if args.fix_cold:
        voice = dsp.fix_cold_breathiness(voice, SR)
        voice = dsp.fix_nasal(voice, SR)

    # 1. notes
    events = None
    if args.transcriber == 'basic-pitch':
        try:
            with tempfile.TemporaryDirectory() as td:
                w = os.path.join(td, 'voice.wav')
                sf.write(w, voice, SR)
                events = transcribe_basic_pitch(w)
        except Exception as exc:  # missing/broken basic-pitch install -> keep going with pYIN
            print(f'basic-pitch unavailable ({type(exc).__name__}: {exc}); using pYIN')
    if events is None:
        events = transcribe_pyin(voice, SR)
    notes = clean_notes(events)
    if len(notes) < 4:
        sys.exit(f'only {len(notes)} melody notes found; is this a sung/hummed melody?')

    # 2. grid + key
    beats, bpm = beat_grid(voice, SR, notes, args.bpm)
    phase = pick_downbeat(beats, notes)
    downs = beats[phase::4]
    first_bar = int(np.searchsorted(downs, notes[0][0] + 0.12, side='right')) - 1
    first_bar = max(0, first_bar - args.intro_bars)
    last_bar = int(np.searchsorted(downs, notes[-1][1] - 0.05, side='right'))  # bar after the melody = outro
    downs = downs[first_bar:last_bar + 2]
    if len(downs) < 3:
        sys.exit('melody too short for an arrangement')
    shift = max(0.0, -float(downs[0]))  # intro before t=0: pad the voice instead of cutting the intro
    downs = downs + shift
    notes = [(s + shift, e + shift, pch, a) for s, e, pch, a in notes]
    voice = np.r_[np.zeros(int(round(shift * SR)), np.float32), voice]
    bars = list(zip(downs[:-1], downs[1:]))

    if args.key:
        tonic, mode = parse_key(args.key)
        key_r = None
    else:
        tonic, mode, key_r = detect_key(notes)
    scale = [(tonic + d) % 12 for d in SCALES[mode]]

    # quantized, in-scale melody for the MIDI / lead line (the sung voice itself is untouched)
    grid = np.concatenate([np.linspace(b0, b1, 17)[:-1] for b0, b1 in bars] + [[bars[-1][1]]])
    q_notes = []
    for s, e, pch, a in notes:
        qs, qe = snap(s, grid), snap(e, grid)
        if qe <= qs:
            qe = grid[min(len(grid) - 1, int(np.searchsorted(grid, qs)) + 1)]
        if pch % 12 not in scale:
            pch = min((pch + d for d in (-1, 1)), key=lambda x: (x % 12 not in scale, abs(x - pch)))
        if q_notes and qs < q_notes[-1][1]:
            q_notes[-1] = (q_notes[-1][0], qs, q_notes[-1][2], q_notes[-1][3])
        if qe > qs:
            q_notes.append((qs, qe, pch, a))
    q_notes = [n for n in q_notes if n[1] > n[0]]

    chords = harmonize(q_notes, bars, tonic, mode)
    key_name = NOTE_NAMES[tonic] + ('m' if mode == 'minor' else '')
    print(f'{len(notes)} notes ({"basic-pitch" if args.transcriber == "basic-pitch" and events is not None else "pYIN"}), '
          f'tempo {bpm:.1f} bpm ({"fixed" if args.bpm else "follows singer"}), key {key_name}'
          + (f' (r={key_r:.2f})' if key_r is not None else ' (forced)'))
    print('bars:', ' | '.join(f'{lbl}' for lbl, *_ in chords))

    # 3. arrangement + render
    pm, melody = build_midi(q_notes, bars, chords, tonic, args.style, bpm, lead_program, rng)
    mel_pm = pretty_midi.PrettyMIDI(initial_tempo=bpm)
    mel_pm.instruments.append(melody)
    mel_pm.write(f'{out_base} (melody).mid')
    if lead_program is not None:
        pm.instruments.append(melody)
    pm.write(f'{out_base}.mid')
    with tempfile.TemporaryDirectory() as td:
        music = render(pm, os.path.join(td, 'music.wav'))

    # 4. mix
    meter = pyln.Meter(SR)
    if args.no_vocal:
        mix = music
    else:
        n = max(music.shape[1], len(voice) + int(2 * SR))
        music = np.pad(music, ((0, 0), (0, n - music.shape[1])))
        v = np.pad(voice, (0, n - len(voice)))
        v = dsp.vocal_tone_chain(v, SR, preset='memo')
        vbus = dsp.vocal_space_bus(v, SR, reverb_db=args.reverb_db, room=args.room,
                                   delay_sec=60.0 / bpm * 0.75, pre_delay_ms=30.0)
        ml = meter.integrated_loudness(music.T)
        vbus *= 10 ** ((ml + args.vocal_db - meter.integrated_loudness(vbus.T)) / 20)
        env = ss.lfilter([1 - 0.9995], [1, -0.9995], np.abs(v))
        env /= np.percentile(env, 99) + 1e-9
        mix = music * (10 ** (-1.5 * np.clip(env, 0, 1) / 20))[None] + vbus
        minus = trim_tail(dsp.master_limiter(music, SR, target_lufs=args.lufs, lim_thresh_db=-3.0, ceiling_db=-1.2))
        dsp.export_wav_mp3(minus, SR, f'{out_base} (minus)', title=f'{os.path.basename(out_base)} (minus)')
    mix = Pedalboard([Compressor(threshold_db=-10, ratio=1.6, attack_ms=30, release_ms=200)])(mix.astype(np.float32), SR)
    mix = dsp.master_limiter(mix, SR, target_lufs=args.lufs, lim_thresh_db=-3.0, ceiling_db=-1.2)
    mix = trim_tail(mix)
    wav, mp3 = dsp.export_wav_mp3(mix, SR, out_base, title=os.path.basename(out_base))
    print(f'final {meter.integrated_loudness(mix.T):.1f} LUFS, {mix.shape[1] / SR:.1f} s -> {wav} {mp3}')
    print(f'midi: {out_base}.mid, {out_base} (melody).mid')


if __name__ == '__main__':
    main()
