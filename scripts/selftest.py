"""Fast automated regression self-test for core music_lab DSP and A/V sync pipelines.

Runs purely on synthetic audio and video generated inside a temporary directory. Scripts that
write into ROOT on their own (output/<title> (klip).*, the work/vocal_on_minus.json last-run
pointer, video_optimize's output/<stem>_polished.*) get _selftest_* names and are cleaned or
restored afterwards, so work/ and output/ end up as they were.

Usage:
  .venv/bin/python -I scripts/selftest.py --quick   # DSP units + melody_to_song render (~10 s)
  .venv/bin/python -I scripts/selftest.py           # + video_optimize, vocal_on_minus, clip_cover e2e (~1 min)
  .venv/bin/python -I scripts/selftest.py --demucs  # + separate_minus --project --voice (Demucs, cached model)
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import librosa
import numpy as np
import pyloudnorm as pyln
import scipy.signal as ss
import soundfile as sf
from pedalboard import PeakFilter, Pedalboard

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import clip_cover
import dsp
import melody_to_song
import video_optimize

SR = 44100


def _synth_vowel(dur_s=2.5, f0=165.0, n_harmonics=25, jitter=0.0, seed=42):
    """Synthesize a speech-paced harmonic vowel waveform with optional F0 jitter."""
    rng = np.random.default_rng(seed)
    n = int(dur_s * SR)
    t = np.arange(n, dtype=np.float64) / SR
    f0_t = np.full(n, f0, dtype=np.float64)
    if jitter > 0.0:
        # frame-level F0 roughness (~115 Hz frame rate) to mimic hoarse vocal folds
        step = max(1, int(SR / 115))
        n_steps = int(np.ceil(n / step)) + 1
        coarse = 1.0 + rng.normal(0.0, jitter, n_steps)
        f0_t = f0 * np.interp(np.arange(n), np.arange(n_steps) * step, coarse)
    phase = 2.0 * np.pi * np.cumsum(f0_t) / SR
    sig = np.zeros(n, dtype=np.float64)
    for k in range(1, n_harmonics + 1):
        if k * f0 >= SR * 0.45:
            break
        sig += np.sin(k * phase) / k
    # Gentle 3-phrase envelope so active/inactive percentiles behave like speech
    env = np.full(n, 0.15, dtype=np.float64)
    for s0, s1 in [(0.10, 0.78), (0.92, 1.62), (1.76, 2.40)]:
        i0, i1 = int(s0 * SR), min(n, int(s1 * SR))
        if i1 > i0:
            w = np.ones(i1 - i0, dtype=np.float64)
            fade = min(int(0.025 * SR), len(w) // 3)
            if fade > 0:
                w[:fade] = np.linspace(0.15, 1.0, fade)
                w[-fade:] = np.linspace(1.0, 0.15, fade)
            env[i0:i1] = w
    out = (sig * env).astype(np.float32)
    rms = float(np.sqrt(np.mean(out ** 2)) + 1e-12)
    return (out * (0.12 / rms)).astype(np.float32)


def _band_noise(n, lo_hz, hi_hz, ref_rms, db_rel, seed):
    rng = np.random.default_rng(seed)
    w = rng.standard_normal(n).astype(np.float64)
    sos = ss.butter(4, [lo_hz, hi_hz], btype='band', fs=SR, output='sos')
    bn = ss.sosfiltfilt(sos, w)
    bn_rms = float(np.sqrt(np.mean(bn ** 2)) + 1e-12)
    target = ref_rms * (10.0 ** (db_rel / 20.0))
    return (bn * (target / bn_rms)).astype(np.float32)


def _synth_syllables(dur_s, seed=7):
    """Synthesize phrase-structured speech-band vocal with room floor for crisp xcorr testing."""
    rng = np.random.default_rng(seed)
    n = int(dur_s * SR)
    t = np.arange(n, dtype=np.float64) / SR
    carrier = np.zeros(n, dtype=np.float64)
    f0 = 170.0
    for k in range(1, 18):
        carrier += np.sin(2.0 * np.pi * k * f0 * t) / (k ** 0.85)
    carrier /= np.max(np.abs(carrier)) + 1e-9

    # Aperiodic multi-length phrases + pauses over a -42 dB room floor (no 0.0 digital silence)
    env = np.full(n, 0.008, dtype=np.float32)
    pos = 0.30
    pattern = [
        (0.28, 0.10, 0.95), (0.55, 1.35, 0.70), (0.18, 0.14, 1.00), (0.42, 0.11, 0.80),
        (0.85, 2.10, 0.90), (0.22, 0.18, 0.65), (0.65, 0.90, 1.00), (0.31, 0.15, 0.75),
        (0.92, 1.65, 0.85), (0.19, 0.12, 0.95), (0.48, 0.80, 0.60), (0.72, 1.40, 1.00),
    ]
    idx = 0
    while pos < dur_s - 0.5:
        width, gap, amp = pattern[idx % len(pattern)]
        width *= (0.9 + 0.2 * float(rng.random()))
        i0 = int(pos * SR)
        i1 = min(n, int((pos + width) * SR))
        if i1 - i0 > 40:
            w = np.ones(i1 - i0, dtype=np.float32)
            fa = min(int(0.008 * SR), len(w) // 3)
            fr = min(int(0.025 * SR), len(w) // 3)
            if fa > 0:
                w[:fa] = np.linspace(0.0, 1.0, fa, dtype=np.float32)
            if fr > 0:
                w[-fr:] = np.linspace(1.0, 0.0, fr, dtype=np.float32)
            env[i0:i1] = np.maximum(env[i0:i1], w * amp)
        pos += width + gap
        idx += 1
    room = rng.normal(0.0, 0.0025, n).astype(np.float32)
    out = (carrier * env * 0.35).astype(np.float32) + room
    return out


def test_diagnose_voice():
    """Verify Praat-style HNR and LTAS nasal excess across 4 synthetic voice profiles."""
    vowel = _synth_vowel(dur_s=2.5, f0=165.0, seed=10)
    ref_rms = float(np.sqrt(np.mean(vowel ** 2)))

    # 1. Clean voice (-45 dB floor)
    clean = (vowel + _band_noise(len(vowel), 200.0, 9000.0, ref_rms, -45.0, seed=11)).astype(np.float32)
    d_clean = dsp.diagnose_voice(clean, SR)
    assert d_clean['hnr_db'] > 20.0, f'Clean HNR too low: {d_clean}'
    assert d_clean['needs_cold_fix'] is False, f'Clean flagged cold_fix: {d_clean}'
    assert d_clean['needs_denasal'] is False, f'Clean flagged denasal: {d_clean}'

    # 2. Breathy voice (-15 dB aspiration 2-9 kHz) -> borderline clean/mildly breathy (15..21 dB)
    breathy = (vowel + _band_noise(len(vowel), 2000.0, 9000.0, ref_rms, -15.0, seed=12)).astype(np.float32)
    d_breathy = dsp.diagnose_voice(breathy, SR)
    assert 15.0 <= d_breathy['hnr_db'] <= 21.0, f'Breathy HNR out of 15..21 dB: {d_breathy}'

    # 3. Hoarse/cold voice (F0 jitter + strong -7 dB aspiration) -> HNR < 15 dB
    hoarse_v = _synth_vowel(dur_s=2.5, f0=165.0, jitter=0.035, seed=13)
    hoarse_rms = float(np.sqrt(np.mean(hoarse_v ** 2)))
    hoarse = (hoarse_v + _band_noise(len(hoarse_v), 2000.0, 9000.0, hoarse_rms, -7.0, seed=14)).astype(np.float32)
    d_hoarse = dsp.diagnose_voice(hoarse, SR)
    assert d_hoarse['hnr_db'] < 15.0, f'Hoarse HNR >= 15 dB: {d_hoarse}'
    assert d_hoarse['needs_cold_fix'] is True, f'Hoarse not flagged cold_fix: {d_hoarse}'

    # 4. Nasal/boxy voice (+13 dB resonance @ 500 Hz and 1400 Hz -> matches +6..+14 dB scale in dsp.py)
    nasal = Pedalboard([
        PeakFilter(500.0, 13.0, 2.5),
        PeakFilter(1400.0, 13.0, 3.0),
    ])(clean[None, :], SR)[0]
    d_nasal = dsp.diagnose_voice(nasal, SR)
    assert d_nasal['needs_denasal'] is True, f'Nasal not flagged denasal: {d_nasal}'
    assert d_nasal['box_500_excess_db'] > 2.5 or d_nasal['honk_1400_excess_db'] > 3.5, (
        f'Nasal excess below threshold: {d_nasal}'
    )
    return (
        f"clean={d_clean['hnr_db']:.1f}dB, breathy={d_breathy['hnr_db']:.1f}dB, "
        f"hoarse={d_hoarse['hnr_db']:.1f}dB, nasal=(500:{d_nasal['box_500_excess_db']:+.1f}, "
        f"1.4k:{d_nasal['honk_1400_excess_db']:+.1f})dB"
    )


def test_f0_cached(td):
    """Verify content-hashed f0 cache isolates different pitches under the same prefix."""
    asr = 22050
    t = np.arange(int(1.5 * asr), dtype=np.float64) / asr
    y1 = (0.3 * np.sin(2.0 * np.pi * 220.0 * t)).astype(np.float32)
    y2 = (0.3 * np.sin(2.0 * np.pi * 330.0 * t)).astype(np.float32)
    base_cache = os.path.join(td, 'selftest_voice_f0.npy')

    m1 = dsp.f0_cached(y1, asr, base_cache)
    m2 = dsp.f0_cached(y2, asr, base_cache)

    files = sorted(glob.glob(os.path.join(td, 'selftest_voice_f0_*.npy')))
    assert len(files) == 2, f'Expected 2 hashed cache files, found {files}'
    hz1 = float(np.nanmedian(librosa.midi_to_hz(m1[~np.isnan(m1)])))
    hz2 = float(np.nanmedian(librosa.midi_to_hz(m2[~np.isnan(m2)])))
    assert abs(hz1 - 220.0) <= 5.0, f'Expected ~220 Hz, got {hz1:.2f} Hz'
    assert abs(hz2 - 330.0) <= 5.0, f'Expected ~330 Hz, got {hz2:.2f} Hz'
    return f'2 distinct cache files ({hz1:.1f} Hz, {hz2:.1f} Hz)'


def test_master_limiter():
    """Verify dsp.master_limiter accuracy at -15 LUFS and -12 LUFS with -1.0 dBFS ceiling."""
    n = int(3.0 * SR)
    t = np.arange(n, dtype=np.float64) / SR
    sig = (0.15 * np.sin(2.0 * np.pi * 220.0 * t) + 0.1 * np.sin(2.0 * np.pi * 330.0 * t))
    sig *= (0.65 + 0.35 * np.sin(2.0 * np.pi * 1.5 * t))
    stereo = np.stack([sig, sig * 0.92]).astype(np.float32)
    meter = pyln.Meter(SR)
    ceil_lin = 10.0 ** (-1.0 / 20.0)

    results = []
    for target in (-15.0, -12.0):
        out = dsp.master_limiter(stereo, SR, target_lufs=target, ceiling_db=-1.0)
        meas = float(meter.integrated_loudness(out.T))
        pk = float(np.abs(out).max())
        assert abs(meas - target) <= 0.15, f'LUFS target {target} got {meas:.2f}'
        assert pk <= ceil_lin + 1e-3, f'Peak {pk:.4f} exceeded ceiling {ceil_lin:.4f}'
        results.append(f'{meas:.2f} LUFS (pk {20*np.log10(pk + 1e-12):.2f} dBFS)')
    return ', '.join(results)


def test_detect_voice_minus_video(td):
    """Verify clip_cover.detect_voice_minus_video finds a +2.35 s camera-to-voice offset."""
    voice = _synth_syllables(dur_s=16.0, seed=21)
    shift_s = 2.35
    cam_seg = voice[int(round(shift_s * SR)):int(round((shift_s + 12.0) * SR))]
    # Color & add noise like a distant phone mic (300-3500 Hz + -18 dB noise)
    sos = ss.butter(3, [300.0, 3500.0], btype='band', fs=SR, output='sos')
    cam_colored = ss.sosfiltfilt(sos, cam_seg).astype(np.float32)
    cam_rms = float(np.sqrt(np.mean(cam_colored ** 2)) + 1e-9)
    cam_audio = (cam_colored + _band_noise(len(cam_colored), 150.0, 7000.0, cam_rms, -18.0, seed=22)).astype(np.float32)

    cam_wav = os.path.join(td, 'cam.wav')
    cam_mov = os.path.join(td, 'cam.mov')
    sf.write(cam_wav, cam_audio, SR)
    # Minimal fast dummy video stream + camera audio at v_start=0
    subprocess.run([
        'ffmpeg', '-loglevel', 'error', '-y',
        '-f', 'lavfi', '-i', 'color=c=black:s=160x120:r=30:d=12.0',
        '-i', cam_wav,
        '-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'stillimage',
        '-c:a', 'pcm_s16le', '-shortest', cam_mov,
    ], check=True)

    res = clip_cover.detect_voice_minus_video(voice, SR, cam_mov)
    assert res is not None, 'detect_voice_minus_video returned None'
    lag, r, ratio = res
    assert abs(lag - shift_s) <= 0.02, f'Expected {shift_s:.3f}s, got {lag:.4f}s'
    assert r > 0.5, f'Low Pearson confidence r={r:.3f}'
    assert ratio > 2.0, f'Low peak ratio={ratio:.2f}'
    return f'lag={lag:+.4f}s (err {(lag - shift_s)*1000:+.1f} ms), r={r:.2f}, peak {ratio:.1f}x'


def test_video_optimize_suite(td):
    """Verify video_optimize A/V sync (pos & neg offset) and portrait rotation metadata."""
    out_dir = os.path.join(td, 'vopt_out')
    os.makedirs(out_dir, exist_ok=True)
    audio = _synth_syllables(dur_s=3.5, seed=31)
    a_wav = os.path.join(td, 'vopt_audio.wav')
    v_only = os.path.join(td, 'v_only.mov')
    clip_pos = os.path.join(td, '_selftest_pos.mov')
    clip_neg = os.path.join(td, '_selftest_neg.mov')
    clip_rot = os.path.join(td, '_selftest_rot.mov')

    sf.write(a_wav, audio, SR)
    subprocess.run([
        'ffmpeg', '-loglevel', 'error', '-y',
        '-f', 'lavfi', '-i', 'testsrc2=size=320x240:rate=30:duration=3.5',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', v_only,
    ], check=True)

    # 5a: Positive audio offset (a_start ~ +0.18 s, v_start = 0)
    subprocess.run([
        'ffmpeg', '-loglevel', 'error', '-y',
        '-i', v_only, '-itsoffset', '0.18', '-i', a_wav,
        '-c:v', 'copy', '-c:a', 'aac', clip_pos,
    ], check=True)

    # 5b: Negative audio offset (v_start ~ +0.15 s, a_start = 0)
    subprocess.run([
        'ffmpeg', '-loglevel', 'error', '-y',
        '-itsoffset', '0.15', '-i', v_only, '-i', a_wav,
        '-c:v', 'copy', '-c:a', 'aac', clip_neg,
    ], check=True)

    # 5c: Portrait rotation metadata (640x360 stream tagged with 90 deg rotation)
    v_land = os.path.join(td, 'land.mov')
    subprocess.run([
        'ffmpeg', '-loglevel', 'error', '-y',
        '-f', 'lavfi', '-i', 'testsrc2=size=640x360:rate=30:duration=0.3',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', v_land,
    ], check=True)
    subprocess.run([
        'ffmpeg', '-loglevel', 'error', '-y',
        '-display_rotation:v:0', '90', '-i', v_land, '-c', 'copy', clip_rot,
    ], check=True)

    try:
        for label, clip, stem in [('pos', clip_pos, '_selftest_pos'), ('neg', clip_neg, '_selftest_neg')]:
            subprocess.run([
                sys.executable, '-I', os.path.join(ROOT, 'scripts', 'video_optimize.py'),
                clip, '--polish-voice', '--out-dir', out_dir,
            ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            fx_path = os.path.join(out_dir, f'{stem}_effects.mp4')
            err, a_lag, v_shift, tol = video_optimize.check_av_sync(clip, fx_path)
            assert abs(err) <= tol, (
                f'{label} A/V sync failed: err={err:+.1f} ms (a_lag={a_lag:+.1f}, '
                f'v_shift={v_shift:+.1f}, tol={tol:.1f})'
            )

        info_pos = video_optimize.check_av_sync(clip_pos, os.path.join(out_dir, '_selftest_pos_effects.mp4'))
        info_neg = video_optimize.check_av_sync(clip_neg, os.path.join(out_dir, '_selftest_neg_effects.mp4'))

        rinfo = video_optimize.probe_streams(clip_rot)
        assert rinfo['width'] == 360 and rinfo['height'] == 640, (
            f'Expected 360x640 rotated display dims, got {rinfo}'
        )
        return (
            f'pos err={info_pos[0]:+.1f}ms (tol {info_pos[3]:.0f}), '
            f'neg err={info_neg[0]:+.1f}ms (tol {info_neg[3]:.0f}), '
            f'portrait={rinfo["width"]}x{rinfo["height"]}'
        )
    finally:
        # video_optimize --polish-voice exports stem_polished.{wav,mp3} into ROOT/output/
        for stem in ('_selftest_pos', '_selftest_neg'):
            for ext in ('wav', 'mp3'):
                p = os.path.join(ROOT, 'output', f'{stem}_polished.{ext}')
                if os.path.exists(p):
                    os.remove(p)


def test_melody_to_song():
    """Verify melody_to_song detect_key, formalize/Viterbi harmonize, and multi-track MIDI generation."""
    # 4 bars at 120 BPM (2.0 s/bar): I (C-E-G), IV (F-A-C), V (G-B-D), I (C-G-E-C)
    pitches = [60, 64, 67, 64, 65, 69, 72, 69, 67, 71, 74, 71, 72, 67, 64, 60]
    notes = [(i * 0.5, i * 0.5 + 0.45, p, 0.85) for i, p in enumerate(pitches)]
    bars = [(b * 2.0, (b + 1) * 2.0) for b in range(4)]

    tonic, mode, key_r = melody_to_song.detect_key(notes)
    assert tonic == 0 and mode == 'major', f'Expected C major, got tonic={tonic}, mode={mode}'
    assert key_r > 0.7, f'Low key confidence r={key_r:.3f}'

    chords = melody_to_song.harmonize(notes, bars, tonic, mode)
    assert len(chords) == 4, f'Expected 4 chords, got {chords}'
    assert chords[-1][0] == 'I', f'Expected final tonic I chord, got {chords}'

    pm, melody = melody_to_song.build_midi(
        notes, bars, chords, tonic, 'pop', 120.0, None, np.random.default_rng(0)
    )
    assert len(pm.instruments) == 4, f'Expected 4 backing tracks, got {len(pm.instruments)}'
    assert all(len(inst.notes) > 0 for inst in pm.instruments), 'Empty instrument track in build_midi'
    assert len(melody.notes) == len(notes), f'Expected {len(notes)} melody notes, got {len(melody.notes)}'
    return (
        f'key=C major (r={key_r:.2f}), chords={"|".join(c[0] for c in chords)}, '
        f'tracks={len(pm.instruments)}+melody({len(melody.notes)} notes)'
    )


# ---------------------------------------------------------------- end-to-end (script subprocesses)
class SkipTest(Exception):
    pass


POINTER = os.path.join(ROOT, 'work', 'vocal_on_minus.json')


def _run_script(name, *argv, timeout=900):
    """Run scripts/<name> like a user would; return stdout, or fail with the output tail."""
    res = subprocess.run([sys.executable, '-I', os.path.join(ROOT, 'scripts', name), *map(str, argv)],
                         capture_output=True, text=True, timeout=timeout)
    if res.returncode != 0:
        tail = '\n'.join((res.stdout + res.stderr).strip().splitlines()[-15:])
        raise AssertionError(f'{name} exited with {res.returncode}:\n{tail}')
    return res.stdout


def _lufs(path):
    y, sr = sf.read(path, always_2d=True)
    return float(pyln.Meter(sr).integrated_loudness(y))


def _ffprobe(path):
    out = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', path],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def _sing(notes, start, note_s=0.45, gap_s=1.2, detune=0.0, total_s=18.0, amp=0.3, seed=0):
    """A sung line: 4 phrases x 4 harmonic notes with vibrato and breath noise."""
    rng = np.random.default_rng(seed)
    y = np.zeros(int(SR * total_s), np.float32)
    t0 = start
    for ph in range(4):
        for k in range(4):
            m = notes[(ph * 2 + k) % len(notes)] + detune
            n = int(note_s * SR)
            tt = np.arange(n) / SR
            f = 440 * 2 ** ((m - 69) / 12) * (1 + 0.004 * np.sin(2 * np.pi * 5.5 * tt))
            phase = 2 * np.pi * np.cumsum(f) / SR
            s = sum(np.sin(h * phase) / h ** 1.3 for h in range(1, 12)) * np.hanning(n) ** 0.3
            s += 0.02 * rng.standard_normal(n)
            i0 = int(t0 * SR)
            y[i0:i0 + n] += (amp * s).astype(np.float32)
            t0 += note_s
        t0 += gap_s
    return y


def _cover_project(td):
    """voice.wav (cover take: later, 5 % slower, +25 cents), orig_vocals.wav, quiet minus.wav."""
    notes = [60, 62, 64, 65, 67, 65, 64, 62]
    proj = os.path.join(td, 'proj')
    os.makedirs(proj, exist_ok=True)
    voice = _sing(notes, start=0.8, note_s=0.45 * 1.05, gap_s=1.2 * 1.05, detune=0.25, seed=1)
    orig = _sing(notes, start=2.0, seed=2)
    t = np.arange(len(orig)) / SR
    hits = (np.sin(2 * np.pi * 2 * t) > 0.95) * np.random.default_rng(3).standard_normal(len(t))
    minus = 0.03 * np.sin(2 * np.pi * 130.8 * t) + 0.015 * np.sin(2 * np.pi * 196 * t) + 0.06 * hits
    sf.write(os.path.join(proj, 'voice.wav'), voice, SR)
    sf.write(os.path.join(proj, 'orig_vocals.wav'), orig, SR)
    sf.write(os.path.join(proj, 'minus.wav'), np.c_[minus, minus].astype(np.float32), SR)
    return proj, voice


def _hum(path):
    """Hummed A-minor melody, 96 bpm, 8 bars, timing jitter (as a person would hum it)."""
    beat = 60 / 96.0
    rng = np.random.default_rng(1)
    mel = [(69, 1), (72, 1), (71, 1), (69, 1), (67, 2), (64, 2), (65, 1), (67, 1), (69, 1), (72, 1), (71, 3), (0, 1),
           (69, 1), (72, 1), (74, 1), (72, 1), (71, 2), (67, 2), (65, 1), (64, 1), (62, 1), (64, 1), (69, 3), (0, 1)]
    y = np.zeros(int((1.3 + sum(b for _, b in mel) * beat + 1.5) * SR))
    t = 1.3
    for m, b in mel:
        if m:
            n = int(b * beat * 0.92 * SR)
            tt = np.arange(n) / SR
            f0 = 440 * 2 ** ((m - 69) / 12) * 2 ** (0.2 / 12 * np.sin(2 * np.pi * 5.5 * tt) * np.clip(tt / 0.3, 0, 1))
            ph = 2 * np.pi * np.cumsum(f0) / SR
            env = np.clip(tt / 0.04, 0, 1) * np.clip((tt[-1] - tt) / 0.08, 0, 1)
            i0 = int((t + rng.normal(0, 0.02)) * SR)
            y[i0:i0 + n] += 0.25 * env * sum(0.6 ** k * np.sin(k * ph) for k in range(1, 9))
        t += b * beat
    sf.write(path, (y + 0.002 * rng.standard_normal(len(y))).astype(np.float32), SR)


def test_melody_render(td):
    """melody_to_song end to end: transcribe a hum, arrange, fluidsynth render, mix at -14 LUFS."""
    if not os.path.exists(melody_to_song.SOUNDFONT) or shutil.which('fluidsynth') is None:
        raise SkipTest('needs soundfonts/FluidR3_GM.sf2 + fluidsynth (sh scripts/get_soundfont.sh)')
    hum = os.path.join(td, 'hum.wav')
    _hum(hum)
    base = os.path.join(td, 'mel', 'song')
    out = _run_script('melody_to_song.py', hum, base)
    assert 'key Am' in out, f'expected key Am:\n{out}'
    n_notes = int(out.split(' notes')[0].split()[-1])
    assert 20 <= n_notes <= 24, f'expected ~22 melody notes, got {n_notes}'
    bars = [b.strip() for b in out.split('bars:')[1].splitlines()[0].split('|')]
    assert bars[-1] == 'i', f'expected the song to end on i: {bars}'
    for f in ('song.wav', 'song.mp3', 'song (minus).wav', 'song.mid', 'song (melody).mid'):
        assert os.path.exists(os.path.join(td, 'mel', f)), f'missing output {f}'
    lufs = _lufs(base + '.wav')
    assert abs(lufs + 14.0) <= 0.5, f'final loudness {lufs:.1f} LUFS, expected -14'
    return f'{n_notes} notes, key Am, {len(bars)} bars ({"|".join(bars)}), {lufs:.1f} LUFS'


def test_vocal_on_minus(td):
    """vocal_on_minus --project end to end: auto vocal level capped at +3 dB, then --vocal-db override."""
    proj, _ = _cover_project(td)
    out1 = _run_script('vocal_on_minus.py', '--project', proj, '--out', os.path.join(td, 'cover', 'auto'))
    line = next(l for l in out1.splitlines() if 'cover vocal' in l)
    auto_db = float(line.split('cover vocal')[1].split('dB')[0])
    ratio_db = float(line.split('balance')[1].split('dB')[0])
    assert ratio_db > 2.5, f'test needs a loud original vocal (ratio {ratio_db:+.1f} dB)'
    assert abs(auto_db - 3.0) < 0.05, f'auto vocal level not capped at +3.0 dB: {line}'
    out2 = _run_script('vocal_on_minus.py', '--project', proj, '--out', os.path.join(td, 'cover', 'manual'),
                       '--vocal-db', '1.0')
    line2 = next(l for l in out2.splitlines() if 'cover vocal' in l)
    assert '+1.0 dB' in line2, f'--vocal-db 1.0 ignored: {line2}'
    for f in ('auto.wav', 'auto.mp3', 'auto - vokal stem.wav', 'manual.wav'):
        assert os.path.exists(os.path.join(td, 'cover', f)), f'missing output {f}'
    lufs = _lufs(os.path.join(td, 'cover', 'auto.wav'))
    assert abs(lufs + 12.0) <= 0.6, f'cover loudness {lufs:.1f} LUFS (vocal_on_minus default target -12)'
    with open(os.path.join(proj, 'vocal_on_minus.json')) as f:
        meta = json.load(f)
    placed = len(meta['placed'])  # one [phrase, start, end, ...] row per placed phrase
    assert placed >= 3, f'only {placed} phrases placed: {meta["placed"]}'
    return (f'balance {ratio_db:+.1f} dB -> auto {auto_db:+.1f} dB (cap), override +1.0 dB, '
            f'{placed}/{meta["n_phrases"]} phrases, {lufs:.1f} LUFS')


def test_clip_cover(td):
    """clip_cover --init (auto voice/video offset, minus intro longer than the lead-in) + portrait render."""
    proj, voice = _cover_project(td)
    vmv = 0.6  # the camera starts 0.6 s after the voice recording
    cam_a = voice[int(vmv * SR):]
    sos = ss.butter(3, [300.0, 3500.0], btype='band', fs=SR, output='sos')
    cam_a = ss.sosfiltfilt(sos, cam_a).astype(np.float32)
    cam_a += _band_noise(len(cam_a), 150.0, 7000.0, float(np.sqrt(np.mean(cam_a ** 2))), -20.0, seed=5)
    cam_wav, land, cam = (os.path.join(td, n) for n in ('cam.wav', 'land.mp4', 'cam.mov'))
    sf.write(cam_wav, cam_a, SR)
    dur = len(cam_a) / SR
    subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i',
                    f'testsrc2=size=640x360:rate=30:duration={dur:.3f}', '-i', cam_wav,
                    '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', '-c:a', 'aac', land], check=True)
    subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-display_rotation:v:0', '90', '-i', land,
                    '-c', 'copy', cam], check=True)
    cfg_path = os.path.join(td, 'clip', 'clip.json')
    title = '_selftest_clip'
    out_files = glob.glob(os.path.join(ROOT, 'output', f'{title} (klip).*'))
    assert not out_files, f'leftover from an earlier run: {out_files}'
    try:
        _run_script('clip_cover.py', '--init', cfg_path, '--voice', os.path.join(proj, 'voice.wav'),
                    '--orig-vocal', os.path.join(proj, 'orig_vocals.wav'), '--minus', os.path.join(proj, 'minus.wav'),
                    '--video', cam, '--title', title)
        with open(cfg_path) as f:
            cfg = json.load(f)
        assert abs(cfg['voice_minus_video'] - vmv) <= 0.02, f'offset {cfg["voice_minus_video"]} != {vmv}'
        assert cfg['intro'] == 0, f'long minus intro should give intro=0, got {cfg["intro"]}'
        assert cfg['fix_cold'] is False, 'fix_cold must stay off unless requested'
        _run_script('clip_cover.py', cfg_path)
        mp4 = os.path.join(ROOT, 'output', f'{title} (klip).mp4')
        info = _ffprobe(mp4)
        v = next(s for s in info['streams'] if s['codec_type'] == 'video')
        assert (v['width'], v['height']) == (720, 1280), f'expected portrait 720x1280, got {v["width"]}x{v["height"]}'
        assert any(s['codec_type'] == 'audio' for s in info['streams']), 'clip has no audio'
        clip_dur = float(info['format']['duration'])
        assert clip_dur > 12.0, f'clip too short: {clip_dur:.1f} s'
        return (f'offset {cfg["voice_minus_video"]:.3f}s (true {vmv}), intro {cfg["intro"]}, '
                f'{v["width"]}x{v["height"]}, {clip_dur:.1f} s')
    finally:
        for f in glob.glob(os.path.join(ROOT, 'output', f'{title} (klip).*')):
            os.remove(f)


def test_separate_minus(td):
    """separate_minus --project --voice (Demucs htdemucs_ft): stems + cleaned take land in the project."""
    proj, voice = _cover_project(td)
    orig, _ = sf.read(os.path.join(proj, 'orig_vocals.wav'))
    minus, _ = sf.read(os.path.join(proj, 'minus.wav'), always_2d=True)
    n = int(10 * SR)
    song = minus[:n] + orig[:n, None]
    song_wav, take = os.path.join(td, 'song.wav'), os.path.join(td, 'take.wav')
    sf.write(song_wav, song.astype(np.float32), SR)
    sf.write(take, voice[:n], SR)
    name = '_selftest_sep'
    new_proj = os.path.join(td, 'sep_proj')
    try:
        _run_script('separate_minus.py', song_wav, '--name', name, '--project', new_proj, '--voice', take,
                    '--work-dir', os.path.join(td, 'separated'), timeout=1800)
        for f in ('orig_vocals.wav', 'minus.wav', 'voice.wav'):
            assert os.path.exists(os.path.join(new_proj, f)), f'project is missing {f}'
        sep_v, _ = sf.read(os.path.join(new_proj, 'orig_vocals.wav'), always_2d=True)
        m = min(n, len(sep_v))
        rms = lambda y: librosa.feature.rms(y=np.ascontiguousarray(y[:m]), frame_length=2205, hop_length=2205)[0]
        r = float(np.corrcoef(rms(sep_v.mean(1)), rms(orig))[0, 1])  # 50 ms loudness envelopes
        assert r > 0.6, f'separated vocal does not follow the original (r={r:.2f})'
        return f'orig_vocals/minus/voice.wav written, vocal envelope r={r:.2f}'
    finally:
        for f in glob.glob(os.path.join(ROOT, 'output', f'{name} (*')):
            os.remove(f)
        for f in glob.glob(os.path.join(ROOT, 'work', f'{name}*_src.wav')):
            os.remove(f)


def main():
    p = argparse.ArgumentParser(description='Run fast synthetic self-tests for music_lab.')
    p.add_argument('--quick', action='store_true',
                   help='Only the fast checks: DSP units + melody_to_song render (~10 s instead of ~1 min)')
    p.add_argument('--demucs', action='store_true',
                   help='Also run separate_minus --project --voice through Demucs (slow; model must be cached)')
    args = p.parse_args()

    # the last-run pointer belongs to the user's real work: snapshot it, restore it at the end
    pointer_backup = open(POINTER, 'rb').read() if os.path.exists(POINTER) else None
    before = {d: set(os.listdir(os.path.join(ROOT, d))) if os.path.isdir(os.path.join(ROOT, d)) else set()
              for d in ('output', 'work')}

    t0 = time.perf_counter()
    failed = 0
    try:
        with tempfile.TemporaryDirectory(prefix='music_lab_selftest_') as td:
            tests = [
                ('1. dsp.diagnose_voice', test_diagnose_voice, True),
                ('2. dsp.f0_cached', lambda: test_f0_cached(td), True),
                ('3. dsp.master_limiter', test_master_limiter, True),
                ('4. clip_cover.detect_voice_minus_video', lambda: test_detect_voice_minus_video(td), True),
                ('5. melody_to_song key/harmonize/MIDI', test_melody_to_song, True),
                ('6. melody_to_song render (hum -> song)', lambda: test_melody_render(td), True),
                ('7. video_optimize sync & rotation', lambda: test_video_optimize_suite(td), not args.quick),
                ('8. vocal_on_minus e2e + vocal level cap', lambda: test_vocal_on_minus(td), not args.quick),
                ('9. clip_cover init + portrait render', lambda: test_clip_cover(td), not args.quick),
                ('10. separate_minus --project --voice (Demucs)', lambda: test_separate_minus(td), args.demucs),
            ]
            for name, fn, enabled in tests:
                if not enabled:
                    why = '--quick' if not name.startswith('10.') else 'needs --demucs'
                    print(f'[SKIP] {name} ({why})')
                    continue
                ts = time.perf_counter()
                try:
                    detail = fn()
                except SkipTest as exc:
                    print(f'[SKIP] {name}: {exc}')
                    continue
                except Exception as exc:  # report every failure, keep going
                    failed += 1
                    print(f'[FAIL] {name} ({time.perf_counter() - ts:.1f}s): {type(exc).__name__}: {exc}')
                    continue
                print(f'[PASS] {name} ({time.perf_counter() - ts:.1f}s): {detail}')
    finally:
        if pointer_backup is not None:
            with open(POINTER, 'wb') as f:
                f.write(pointer_backup)
        elif os.path.exists(POINTER):
            os.remove(POINTER)
        for d, names in before.items():
            path = os.path.join(ROOT, d)
            new = sorted(set(os.listdir(path)) - names) if os.path.isdir(path) else []
            if new:  # not ours to delete: may belong to a run the user started meanwhile
                print(f'[WARN] new entries in {d}/ during the self-test: {new}')

    total = time.perf_counter() - t0
    if failed:
        print(f'{failed} self-test(s) FAILED ({total:.1f}s)')
        sys.exit(1)
    print(f'All self-tests passed in {total:.1f}s')


if __name__ == '__main__':
    main()
