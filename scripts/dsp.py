"""Shared DSP, voice diagnostics, pitch/EQ chains, and mastering utilities for music_lab."""
import hashlib
import os
import subprocess
import numpy as np
import librosa
import soundfile as sf
import scipy.signal as ss
import pyloudnorm as pyln
from scipy.ndimage import uniform_filter1d
from pedalboard import (
    Pedalboard, HighpassFilter, LowpassFilter, PeakFilter, HighShelfFilter,
    LowShelfFilter, Compressor, Reverb, Delay, Gain, Limiter, Chorus,
)

# User-approved dry defaults (references/vokal-reverb-didi.md)
DEFAULT_REVERB_DB = -18.0
DEFAULT_ROOM = 0.5
DEFAULT_DELAY_DB = -26.0
DEFAULT_COLD_REDUCE_DB = 7.0
DEFAULT_DENASAL_STRENGTH = 0.7


def load_mono(path, sr=44100):
    """Load an audio file as a 1D float32 array resampled to `sr`."""
    try:
        y, orig_sr = sf.read(path, always_2d=True)
        y = y.mean(1).astype(np.float32)
        if orig_sr != sr:
            y = librosa.resample(y, orig_sr=orig_sr, target_sr=sr).astype(np.float32)
        return y
    except Exception:
        y, _ = librosa.load(path, sr=sr, mono=True)
        return y.astype(np.float32)


def f0_pyin(y, sr=22050, fmin=65, fmax=1000, frame_length=2048, hop_length=256):
    """Track fundamental frequency with pYIN and return MIDI notes (NaN when unvoiced)."""
    f, v, _ = librosa.pyin(
        y, fmin=fmin, fmax=fmax, sr=sr, frame_length=frame_length, hop_length=hop_length
    )
    return librosa.hz_to_midi(np.where(v, f, np.nan))


def f0_cached(y, sr, cache_path, fmin=65, fmax=1000, hop_length=256):
    """Compute or load a cached pYIN MIDI track.

    The cache is keyed by the audio content and analysis settings: `cache_path` 'tmp/orig_f0.npy'
    becomes 'tmp/orig_f0_<hash>.npy'. A different song, a re-recorded take or a --fix-cold
    cleaned voice therefore never reuses a stale pitch track.
    """
    y = np.ascontiguousarray(y, dtype=np.float32)
    h = hashlib.sha1(y.tobytes())
    h.update(f'{sr}|{fmin}|{fmax}|{hop_length}'.encode())
    root, ext = os.path.splitext(cache_path)
    path = f'{root}_{h.hexdigest()[:12]}{ext or ".npy"}'
    if os.path.exists(path):
        return np.load(path)
    res = f0_pyin(y, sr=sr, fmin=fmin, fmax=fmax, hop_length=hop_length)
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    np.save(path, res)
    return res


def _harmonic_comb_and_f0(y, sr, nfft=4096, hop=512):
    """Shared pYIN interpolation and STFT grid for the cold-fix harmonic comb."""
    asr = 22050
    ya = y if sr == asr else librosa.resample(y, orig_sr=sr, target_sr=asr)
    f0, vflag, _ = librosa.pyin(ya, fmin=70, fmax=800, sr=asr, frame_length=2048, hop_length=256)
    tf = librosa.frames_to_time(np.arange(len(f0)), sr=asr, hop_length=256)

    S = librosa.stft(y, n_fft=nfft, hop_length=hop)
    ts = librosa.frames_to_time(np.arange(S.shape[1]), sr=sr, hop_length=hop)
    f0i = np.interp(ts, tf, np.nan_to_num(f0, nan=0.0))
    vp = np.interp(ts, tf, vflag.astype(float))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=nfft)
    return S, freqs, f0i, vp


def _comb_weights(freqs, f0_hz):
    k = np.maximum(np.round(freqs / f0_hz), 1)
    d = np.abs(freqs - k * f0_hz)
    w = np.maximum(22.0, 0.025 * k * f0_hz)
    return np.exp(-0.5 * (d / w) ** 2)


def fix_cold_breathiness(y, sr, reduce_db=DEFAULT_COLD_REDUCE_DB):
    """Attenuate inter-harmonic noise below 5.5 kHz on voiced frames (cold/hoarse fix)."""
    if reduce_db <= 0 or len(y) == 0:
        return y.astype(np.float32)
    nfft = 4096 if sr >= 40000 else 2048
    hop = 512 if sr >= 40000 else 256
    S, freqs, f0i, vp = _harmonic_comb_and_f0(y, sr, nfft=nfft, hop=hop)

    floor = 10 ** (-reduce_db / 20)
    band = np.clip((5500 - freqs) / 1500, 0, 1)
    G = np.ones(S.shape, np.float32)
    for i in range(S.shape[1]):
        if f0i[i] < 60 or vp[i] < 0.5:
            continue
        comb = _comb_weights(freqs, f0i[i])
        m = floor + (1 - floor) * comb
        strength = band * vp[i]
        G[:, i] = 1 - strength * (1 - m)
    G[freqs < 70] = 1.0
    G = uniform_filter1d(G, 3, axis=1)
    return librosa.istft(S * G, hop_length=hop, length=len(y)).astype(np.float32)


def _octave_envelope_and_active(y, sr, nfft=2048, hop=256):
    """Compute log-magnitude STFT, 1-octave spectral envelope, and active-frame mask."""
    S = librosa.stft(y, n_fft=nfft, hop_length=hop)
    L = 20 * np.log10(np.abs(S) + 1e-9)
    freqs = librosa.fft_frequencies(sr=sr, n_fft=nfft)
    lo = np.searchsorted(freqs, freqs / (2 ** 0.5))
    hi = np.clip(np.searchsorted(freqs, freqs * (2 ** 0.5)), lo + 1, len(freqs))
    cs = np.vstack([np.zeros((1, L.shape[1])), np.cumsum(L, 0)])
    env = (cs[hi] - cs[lo]) / (hi - lo)[:, None]
    frame_db = 10 * np.log10((np.abs(S) ** 2).mean(0) + 1e-12)
    active = frame_db > np.percentile(frame_db, 40)
    return S, L, freqs, env, active


def fix_nasal(y, sr, strength=DEFAULT_DENASAL_STRENGTH, return_stats=False):
    """Tame congested/nasal resonances (350-1900 Hz) and restore 2.8 kHz presence."""
    y = y.astype(np.float32)
    if strength <= 0 or len(y) == 0:
        stats = {'avg_red_db': 0.0, 'max_red_db': 0.0}
        return (y, stats) if return_stats else y

    nfft, hop = 2048, 256
    thr, max_red = 3.0, 7.0 * strength
    S, L, freqs, env, active = _octave_envelope_and_active(y, sr, nfft=nfft, hop=hop)
    band = np.clip(np.minimum((freqs - 300) / 100, (2100 - freqs) / 300), 0, 1)[:, None]
    red = np.clip(L - env - thr, 0, max_red) * band * active[None, :].astype(float)
    red = uniform_filter1d(uniform_filter1d(red, 5, axis=1), 3, axis=0)

    out = librosa.istft(S * (10 ** (-red / 20)), hop_length=hop, length=len(y)).astype(np.float32)
    out = Pedalboard([
        PeakFilter(520, -2.0 * strength, 1.3),
        PeakFilter(1350, -2.0 * strength, 1.2),
        PeakFilter(2800, 3.5 * strength, 0.9),
    ])(out[None], sr)[0]
    out *= np.sqrt((y ** 2).mean() / ((out ** 2).mean() + 1e-12))
    out = out.astype(np.float32)

    if return_stats:
        bmask = band[:, 0] > 0.5
        amask = active
        avg_red = float(red[bmask][:, amask].mean()) if (np.any(bmask) and np.any(amask)) else 0.0
        return out, {'avg_red_db': avg_red, 'max_red_db': float(red.max())}
    return out


def diagnose_voice(y, sr):
    """Analyze HNR, nasal/boxy resonances, high-mid ring, and pitch stability."""
    y = np.asarray(y, dtype=np.float32)
    if len(y) < int(0.25 * sr) or float(np.max(np.abs(y))) < 1e-6:
        return {
            'hnr_db': 0.0,
            'box_500_excess_db': 0.0,
            'honk_1400_excess_db': 0.0,
            'ring_2800_rel_db': 0.0,
            'median_cents_error': 0.0,
            'needs_cold_fix': False,
            'needs_denasal': False,
            'summary': 'voice too short or silent for diagnostics',
        }

    # 1. HNR (Praat-style): normalized autocorrelation at one pitch period, median over voiced frames.
    #    Calibrated on synthetic voices: clean ~28 dB, breath noise -15 dB ~17 dB, hoarse (-8 dB) ~11 dB.
    #    (The harmonic-comb ratio used by fix_cold_breathiness saturates near 14 dB even for a clean
    #    voice, so it cannot be used as a diagnostic.)
    asr = 22050
    ya = y if sr == asr else librosa.resample(y, orig_sr=sr, target_sr=asr)
    f0, vflag, _ = librosa.pyin(ya, fmin=70, fmax=800, sr=asr, frame_length=2048, hop_length=256)
    win = 1024
    hnr_frames = []
    for i in np.flatnonzero(vflag & np.isfinite(f0))[::2]:
        a = i * 256 - win // 2
        period = asr / f0[i]
        if a < 0 or a + win + int(period * 1.1) + 2 > len(ya):
            continue
        seg = ya[a:a + win]
        e0 = float(np.dot(seg, seg))
        best = -1.0
        for tau in range(int(period * 0.92), int(period * 1.08) + 2):
            x2 = ya[a + tau:a + tau + win]
            best = max(best, float(np.dot(seg, x2)) / np.sqrt(e0 * float(np.dot(x2, x2)) + 1e-12))
        r = min(max(best, 1e-3), 0.9999)
        hnr_frames.append(10.0 * np.log10(r / (1.0 - r)))
    n_voiced = len(hnr_frames)
    hnr_db = float(np.median(hnr_frames)) if n_voiced >= 5 else 20.0

    # 2. Nasal / boxy / ring measurements on the long-term average spectrum (active frames).
    #    Resonance excess = 1/3-octave LTAS minus 1.5-octave trend. Per-frame bin excess is dominated
    #    by the harmonic/valley structure and barely moves (+1.7 dB for a +14 dB resonance); the LTAS
    #    measure tracks it (+2.4..+6 dB for +6..+14 dB resonances; clean voices -1.2..+2.5 dB).
    S, L, freqs, env, active = _octave_envelope_and_active(y, sr, nfft=2048, hop=256)
    pwr = (np.abs(S) ** 2)[:, active] if np.any(active) else (np.abs(S) ** 2)
    ltas = 10 * np.log10(pwr.mean(1) + 1e-12)
    logf = np.log2(np.maximum(freqs, 20.0))

    def _oct_smooth(width_oct):
        lo = np.searchsorted(logf, logf - width_oct / 2, side='left')
        hi = np.searchsorted(logf, logf + width_oct / 2, side='right')
        cs = np.r_[0.0, np.cumsum(ltas)]
        return (cs[hi] - cs[lo]) / np.maximum(hi - lo, 1)

    excess = _oct_smooth(1 / 3) - _oct_smooth(1.5)

    m_box = (freqs >= 400) & (freqs <= 600)
    m_honk = (freqs >= 1100) & (freqs <= 1700)
    m_mid = (freqs >= 800) & (freqs <= 1200)
    m_ring = (freqs >= 2000) & (freqs <= 3500)

    box_excess = float(np.mean(excess[m_box])) if np.any(m_box) else 0.0
    honk_excess = float(np.mean(excess[m_honk])) if np.any(m_honk) else 0.0
    p_mid = float(np.mean(pwr[m_mid])) if np.any(m_mid) else 1e-12
    p_ring = float(np.mean(pwr[m_ring])) if np.any(m_ring) else 1e-12
    ring_rel = float(10.0 * np.log10((p_ring + 1e-12) / (p_mid + 1e-12)))

    # 3. Pitch deviation (median cents from nearest semitone), reusing the pYIN track from step 1
    tuning = float(librosa.estimate_tuning(y=ya, sr=asr))
    midi = librosa.hz_to_midi(np.where(vflag, f0, np.nan))
    vmask = ~np.isnan(midi)
    if np.sum(vmask) >= 5:
        dev = np.abs(((midi[vmask] - tuning + 0.5) % 1) - 0.5) * 100.0
        cents_err = float(np.median(dev))
    else:
        cents_err = 0.0

    # Advisory only: scripts never switch the cleanup on by themselves.
    # The 2-3.5 kHz vs 1 kHz level is NOT a trigger: a normal voice's spectral tilt
    # already puts it around -8..-16 dB. It is still reported in the summary.
    # HNR 15: the user's approved cold take («Белтепа», 2026-11-14) maps to ~14 dB on this scale.
    needs_cold = bool(n_voiced >= 5 and hnr_db < 15.0)
    needs_denasal = bool(box_excess > 2.5 or honk_excess > 3.5)
    rec = '--fix-cold suggested' if (needs_cold or needs_denasal) else 'clean (no cold fix needed)'
    summary = (
        f'HNR {hnr_db:.1f} dB, 500Hz {box_excess:+.1f} dB, 1.4kHz {honk_excess:+.1f} dB, '
        f'2-3.5kHz {ring_rel:+.1f} dB vs 1kHz, pitch {cents_err:.0f} cents -> {rec}'
    )
    return {
        'hnr_db': round(float(hnr_db), 2),
        'box_500_excess_db': round(box_excess, 2),
        'honk_1400_excess_db': round(honk_excess, 2),
        'ring_2800_rel_db': round(ring_rel, 2),
        'median_cents_error': round(cents_err, 1),
        'needs_cold_fix': needs_cold,
        'needs_denasal': needs_denasal,
        'summary': summary,
    }


def spectral_deess(y, sr, lo=5000, hi=11000, thr_db=-7.0, max_red=8.0):
    """Dynamic STFT de-esser acting only when sibilance band exceeds threshold."""
    S = librosa.stft(y, n_fft=1024, hop_length=256)
    freqs = librosa.fft_frequencies(sr=sr, n_fft=1024)
    hb = (freqs >= lo) & (freqs <= hi)
    if not np.any(hb):
        return y.astype(np.float32)
    eh = 10 * np.log10((np.abs(S[hb]) ** 2).sum(0) + 1e-12)
    et = 10 * np.log10((np.abs(S) ** 2).sum(0) + 1e-12)
    red = uniform_filter1d(np.clip((eh - et) - thr_db, 0, max_red), 3)
    g = np.ones(S.shape, dtype=np.float32)
    g[freqs >= lo - 500] = 10 ** (-red / 20)
    return librosa.istft(S * g, hop_length=256, length=len(y)).astype(np.float32)


def match_eq_fir(target_y, source_y, sr, max_db=6.0, amount=0.6):
    """Apply smoothed 1/3-octave LTAS match-EQ from `target_y` onto `source_y`."""
    def ltas(x):
        S = np.abs(librosa.stft(x, n_fft=4096, hop_length=1024)) ** 2
        r = librosa.feature.rms(y=x, frame_length=4096, hop_length=1024)[0][:S.shape[1]]
        keep = r > np.percentile(r[r > 0], 50) if np.any(r > 0) else slice(None)
        return 10 * np.log10(S[:, keep].mean(1) + 1e-12)

    freqs = librosa.fft_frequencies(sr=sr, n_fft=4096)
    diff = ltas(target_y) - ltas(source_y)
    logf = np.log2(np.maximum(freqs, 20.0))
    curve = np.array([diff[np.abs(logf - lf) < 1 / 6].mean() for lf in logf])
    band = (freqs > 100) & (freqs < min(14000, sr * 0.45))
    curve -= np.average(curve[band], weights=1 / np.maximum(freqs[band], 1))
    curve = np.clip(np.where(band, curve, 0.0), -max_db, max_db) * amount
    norm_f = freqs / (sr / 2)
    norm_f[-1] = 1.0
    fir = ss.firwin2(2047, norm_f, 10 ** (curve / 20))
    return ss.fftconvolve(source_y, fir, mode='same').astype(np.float32)


def vocal_tone_chain(y, sr, preset='memo'):
    """Apply EQ, compression, and spectral de-essing to a mono 1D vocal array."""
    x = np.asarray(y, dtype=np.float32)
    if preset == 'memo':
        x = Pedalboard([
            HighpassFilter(85),
            PeakFilter(190, -4.0, 0.9),
            PeakFilter(380, -2.5, 1.2),
            Compressor(threshold_db=-24, ratio=3.5, attack_ms=5, release_ms=90),
            PeakFilter(1100, -1.0, 1.4),
            PeakFilter(3200, 3.0, 0.8),
            HighShelfFilter(9000, 3.5, 0.7),
            LowShelfFilter(140, 1.0, 0.7),
        ])(x[None, :], sr)[0]
        x = spectral_deess(x, sr, thr_db=-8.0)
        x = Pedalboard([Compressor(threshold_db=-16, ratio=2.0, attack_ms=20, release_ms=160)])(x[None, :], sr)[0]
    elif preset == 'mix':
        x = Pedalboard([
            HighpassFilter(90),
            PeakFilter(320, -2.0, 1.0),
            Compressor(threshold_db=-22, ratio=4.0, attack_ms=4, release_ms=80),
        ])(x[None, :], sr)[0]
        x = spectral_deess(x, sr, thr_db=-6.0)
        x = Pedalboard([
            PeakFilter(3500, 2.0, 0.8),
            HighShelfFilter(10000, 2.5, 0.7),
            LowShelfFilter(180, 1.0, 0.7),
            Compressor(threshold_db=-14, ratio=2.0, attack_ms=20, release_ms=150),
        ])(x[None, :], sr)[0]
    else:
        raise ValueError(f'Unknown vocal_tone_chain preset: {preset}')
    return x.astype(np.float32)


def _shift_right_no_wrap(arr, samples):
    if samples <= 0 or samples >= len(arr):
        return arr
    return np.concatenate([np.zeros(samples, dtype=arr.dtype), arr[:-samples]])


def vocal_space_bus(
    y,
    sr,
    reverb_db=DEFAULT_REVERB_DB,
    room=DEFAULT_ROOM,
    delay_db=None,
    delay_sec=0.375,
    pre_delay_ms=32.0,
    stereo_double_db=None,
):
    """Build stereo (2, N) vocal bus with pre-delayed reverb, filtered delay, and optional double."""
    if delay_db is None:
        delay_db = reverb_db - 8.0
    x = np.asarray(y, dtype=np.float32)
    st = np.stack([x, x])
    pre = np.zeros((2, int(pre_delay_ms / 1000.0 * sr)), np.float32)
    rev = Pedalboard([
        HighpassFilter(280),
        LowpassFilter(8800),
        Reverb(room_size=room, damping=0.5, wet_level=1.0, dry_level=0.0, width=1.0),
    ])(np.concatenate([pre, st], 1)[:, :st.shape[1]], sr)

    dly = Pedalboard([
        HighpassFilter(400),
        LowpassFilter(5000),
        Delay(delay_seconds=delay_sec, feedback=0.28, mix=1.0),
    ])(st, sr)
    dly[1] = _shift_right_no_wrap(dly[1], int(0.02 * sr))

    out = st + (10 ** (reverb_db / 20)) * rev + (10 ** (delay_db / 20)) * dly
    if stereo_double_db is not None:
        dbl = Pedalboard([
            Chorus(rate_hz=0.6, depth=0.12, centre_delay_ms=14, feedback=0.0, mix=1.0)
        ])(st, sr)
        dbl[1] = _shift_right_no_wrap(dbl[1], int(0.008 * sr))
        out = out + (10 ** (stereo_double_db / 20)) * dbl
    return out.astype(np.float32)


def master_limiter(stereo_2xN, sr, target_lufs=-14.0, lim_thresh_db=-2.0, ceiling_db=-1.0, n_iter=6):
    """Iterate input gain into Pedalboard Limiter so output hits `target_lufs` without clipping."""
    x = np.asarray(stereo_2xN, dtype=np.float32)
    meter = pyln.Meter(sr)
    cur_lufs = meter.integrated_loudness(x.T)
    if not np.isfinite(cur_lufs):
        return x

    g_db = float(target_lufs - cur_lufs)
    ceil_lin = 10 ** (ceiling_db / 20)
    out = x
    for _ in range(n_iter):
        out = Pedalboard([
            Gain(g_db),
            Limiter(threshold_db=lim_thresh_db, release_ms=130),
        ])(x, sr)
        pk = float(np.abs(out).max())
        if pk > ceil_lin:
            out = out * (ceil_lin / pk)
        lufs_out = meter.integrated_loudness(out.T)
        if not np.isfinite(lufs_out):
            break
        err = float(target_lufs - lufs_out)
        if abs(err) < 0.1:
            break
        g_db += err
    return out.astype(np.float32)


def export_wav_mp3(stereo_2xN, sr, out_base_no_ext, title=None):
    """Export stereo (2, N) audio to 24-bit WAV and 320 kbps MP3."""
    parent = os.path.dirname(os.path.abspath(out_base_no_ext))
    if parent:
        os.makedirs(parent, exist_ok=True)
    wav = f'{out_base_no_ext}.wav'
    mp3 = f'{out_base_no_ext}.mp3'
    sf.write(wav, np.asarray(stereo_2xN, dtype=np.float32).T, sr, subtype='PCM_24')
    meta_title = title if title is not None else os.path.basename(out_base_no_ext)
    subprocess.run(
        ['ffmpeg', '-loglevel', 'error', '-y', '-i', wav, '-c:a', 'libmp3lame', '-b:a', '320k',
         '-metadata', f'title={meta_title}', mp3],
        check=True,
    )
    return wav, mp3
