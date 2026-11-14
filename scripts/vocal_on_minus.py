"""Put an a-cappella vocal recording onto a minus (instrumental) with studio-style processing.

Pipeline:
  1. Optional voice diagnostics and cold/nasal cleanup (--fix-cold).
  2. Phrase detection on the cleaned (Demucs) vocal.
  3. DTW alignment against the original singer's vocal stem; the voice is split at the
     song's long instrumental break if the singer skipped it.
  4. Per phrase: gentle pitch correction (toward the original melody, vibrato kept)
     + variable time-stretch onto the song timeline (Rubber Band R3, formant-preserving).
  5. Optional Match-EQ toward the original vocal tone, de-esser, compression, EQ, dry-first
     plate reverb + delay.
  6. Mix over the minus with light sidechain ducking, master to target loudness.

Usage:
  .venv/bin/python -I scripts/vocal_on_minus.py --project work/my_song --out "My Cover"
  .venv/bin/python -I scripts/vocal_on_minus.py --voice v.wav --orig-vocal ov.wav --minus m.wav --out "My Cover"
  .venv/bin/python -I scripts/vocal_on_minus.py --config work/my_song/config.json
"""
import argparse
import json
import os
import subprocess
import sys
import numpy as np
import soundfile as sf
import librosa
import scipy.signal as ss
import pyloudnorm as pyln
from scipy.ndimage import median_filter, uniform_filter1d
from pedalboard import Pedalboard, Compressor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dsp

SR = 44100
ASR = 22050
HOP = 256          # analysis rate / hop (11.6 ms)
RB = ['rubberband', '-q', '-3']
STEPS = np.array([[1, 1], [1, 2], [2, 1]])


def fr2t(i):
    return i * HOP / ASR


def mmss(x):
    s = str(x)
    return float(s.split(':')[0]) * 60 + float(s.split(':')[1]) if ':' in s else float(s)


def phrases(y, top_db=35, min_len=0.3):
    iv = librosa.effects.split(y, top_db=top_db, frame_length=2048, hop_length=HOP)
    return [(a / ASR, b / ASR) for a, b in iv if (b - a) / ASR >= min_len]


def feats(y):
    c = librosa.feature.chroma_cens(y=y, sr=ASR, hop_length=HOP)
    on = librosa.onset.onset_strength(y=y, sr=ASR, hop_length=HOP)[None, :c.shape[1]]
    r = librosa.feature.rms(y=y, hop_length=HOP)[0][None, :c.shape[1]]
    r = (r > np.percentile(r, 35)).astype(float)
    on = on / (on.max() + 1e-9)
    return np.vstack([c, 0.6 * r, 0.4 * on])


def feats_local(y, midi):
    n = len(midi)
    pcs = np.arange(12)[:, None]
    d = np.abs(((np.nan_to_num(midi)[None, :] % 12) - pcs + 6) % 12 - 6)
    pc = np.exp(-d ** 2 / (2 * 0.45 ** 2)) * (~np.isnan(midi))[None, :]
    on = librosa.onset.onset_strength(y=y, sr=ASR, hop_length=HOP)
    on = np.pad(on, (0, max(0, n - len(on))))[:n]
    on = np.clip(on / (np.percentile(on, 99) + 1e-9), 0, 1.5)
    return np.vstack([pc, 0.7 * (~np.isnan(midi))[None, :], 0.5 * on[None, :]])


def _resolve_config(args):
    cfg = {
        'voice': None,
        'orig_vocal': None,
        'minus': None,
        'out': 'cover_mix',
        'work_dir': 'work',
        'lufs': -12.0,
        'pitch_strength': 0.75,
        'reverb_db': dsp.DEFAULT_REVERB_DB,
        'room': dsp.DEFAULT_ROOM,
        'delay_db': None,  # None -> reverb_db - 8 (follows --reverb-db, -26 dB by default)
        'align': os.environ.get('ALIGN', 'global'),
        'fix_cold': False,
        'match_eq': True,
    }
    if args.project:
        proj = args.project.rstrip('/')
        cfg['work_dir'] = proj
        p_cfg = os.path.join(proj, 'config.json')
        if os.path.exists(p_cfg):
            cfg.update(json.load(open(p_cfg)))
        for key, candidates in [
            ('voice', ['voice.wav', 'vocal.wav', 'vocals.wav']),
            ('orig_vocal', ['orig_vocals.wav', 'orig_vocal.wav', 'origv.wav']),
            ('minus', ['minus.wav', 'no_vocals.wav']),
        ]:
            for cand in candidates:
                cp = os.path.join(proj, cand)
                if os.path.exists(cp):
                    cfg[key] = cp
                    break
        if 'out' not in cfg or cfg['out'] == 'cover_mix':
            cfg['out'] = os.path.basename(os.path.abspath(proj))
    if args.config:
        with open(args.config) as f:
            loaded = json.load(f)
        cfg.update(loaded)
        if 'work_dir' not in loaded and not args.project:
            cfg['work_dir'] = os.path.dirname(os.path.abspath(args.config))

    overrides = {
        'voice': args.voice,
        'orig_vocal': args.orig_vocal,
        'minus': args.minus,
        'out': args.out,
        'lufs': args.lufs,
        'pitch_strength': args.pitch_strength,
        'reverb_db': args.reverb_db,
        'room': args.room,
        'delay_db': args.delay_db,
        'align': args.align,
    }
    for k, v in overrides.items():
        if v is not None:
            cfg[k] = v
    if args.fix_cold:
        cfg['fix_cold'] = True
    if args.no_match_eq:
        cfg['match_eq'] = False
    if cfg.get('delay_db') is None:
        cfg['delay_db'] = cfg['reverb_db'] - 8.0
    return cfg


def main():
    p = argparse.ArgumentParser(
        description='Align, tune, process, and mix an a-cappella vocal onto an instrumental minus.'
    )
    p.add_argument('--config', help='Path to JSON config file')
    p.add_argument('--project', help='Project directory under work/ (auto-discovers voice/orig_vocals/minus.wav)')
    p.add_argument('--voice', help='Cleaned user vocal WAV path')
    p.add_argument('--orig-vocal', help='Original singer vocal stem WAV path')
    p.add_argument('--minus', help='Instrumental minus WAV path')
    p.add_argument('--out', help='Output track name (or path without extension)')
    p.add_argument('--lufs', type=float, default=None, help='Target loudness in LUFS (default: -12.0)')
    p.add_argument('--pitch-strength', type=float, default=None, help='Pitch correction strength 0..1 (default: 0.75)')
    p.add_argument('--reverb-db', type=float, default=None, help=f'Reverb level in dB (default: {dsp.DEFAULT_REVERB_DB})')
    p.add_argument('--room', type=float, default=None, help=f'Reverb room size 0..1 (default: {dsp.DEFAULT_ROOM})')
    p.add_argument('--delay-db', type=float, default=None,
                   help=f'Delay level in dB (default: reverb_db - 8, i.e. {dsp.DEFAULT_DELAY_DB})')
    p.add_argument('--align', choices=['global', 'local', 'shift'], default=None,
                   help='Alignment strategy (default: global)')
    p.add_argument('--fix-cold', action='store_true', help='Apply cold breathiness + denasal cleanup before alignment')
    p.add_argument('--no-match-eq', action='store_true', help='Disable LTAS Match-EQ toward the original vocal')
    args = p.parse_args()

    # Resolve user-given paths against the caller's cwd before switching to the project root.
    for attr in ('config', 'project', 'voice', 'orig_vocal', 'minus'):
        if getattr(args, attr):
            setattr(args, attr, os.path.abspath(getattr(args, attr)))
    if args.out and os.path.dirname(args.out):
        args.out = os.path.abspath(args.out)
    os.chdir(ROOT)
    cfg = _resolve_config(args)

    missing = [k for k in ('voice', 'orig_vocal', 'minus') if not cfg[k] or not os.path.exists(cfg[k])]
    if missing:
        details = ', '.join(f'{k}={cfg[k]}' for k in missing)
        sys.exit(
            f'Missing input audio file(s): {details}\n'
            f'Hint: pass --project work/<name> or --voice / --orig-vocal / --minus '
            f'(run scripts/separate_minus.py first to extract stems).'
        )

    work_dir = cfg['work_dir']
    tmp_dir = os.path.join(work_dir, 'tmp')
    shifts_path = os.path.join(work_dir, 'phrase_shifts.json')
    os.makedirs(tmp_dir, exist_ok=True)
    os.makedirs('output', exist_ok=True)

    voice = dsp.load_mono(cfg['voice'], sr=SR)
    origv = dsp.load_mono(cfg['orig_vocal'], sr=SR)
    minus, msr = sf.read(cfg['minus'], always_2d=True)
    if msr != SR:
        minus = np.column_stack([
            librosa.resample(minus[:, ch], orig_sr=msr, target_sr=SR) for ch in range(minus.shape[1])
        ])
    song_len = len(minus)

    diag = dsp.diagnose_voice(voice, SR)
    print(f'diagnose: {diag["summary"]}')
    if cfg['fix_cold']:
        print('applying cold_fix + denasal...')
        voice = dsp.fix_cold_breathiness(voice, SR, reduce_db=dsp.DEFAULT_COLD_REDUCE_DB)
        voice = dsp.fix_nasal(voice, SR, strength=dsp.DEFAULT_DENASAL_STRENGTH)

    va = librosa.resample(voice, orig_sr=SR, target_sr=ASR)
    oa = librosa.resample(origv, orig_sr=SR, target_sr=ASR)

    # ---------- 1. phrases ----------
    vph = phrases(va)
    oph = phrases(oa)
    print(f'voice phrases: {len(vph)}, original phrases: {len(oph)}')
    if not vph or not oph:
        sys.exit('Could not detect enough voiced phrases in voice or original vocal.')

    # ---------- 2. alignment ----------
    FV, FO = feats(va), feats(oa)

    def dtw_map(v0, v1, o0, o1):
        a0 = max(0, int(v0 * ASR / HOP))
        a1 = min(FV.shape[1], int(v1 * ASR / HOP))
        b0 = max(0, int(o0 * ASR / HOP))
        b1 = min(FO.shape[1], int(o1 * ASR / HOP))
        if a1 <= a0 + 2 or b1 <= b0 + 2:
            return np.inf, None, None
        try:
            D, wp = librosa.sequence.dtw(X=FV[:, a0:a1], Y=FO[:, b0:b1], metric='cosine', step_sizes_sigma=STEPS)
        except librosa.util.exceptions.ParameterError:
            return np.inf, None, None
        wp = wp[::-1]
        return D[-1, -1] / len(wp), fr2t(wp[:, 0] + a0), fr2t(wp[:, 1] + b0)

    gaps = [(oph[i][1], oph[i + 1][0]) for i in range(len(oph) - 1) if oph[i + 1][0] - oph[i][1] > 10]
    pad = 0.3
    segments = []
    if gaps and len(vph) > 2:
        g0, g1 = gaps[0]
        total_v = vph[-1][1] - vph[0][0]
        best = None
        for k in range(1, len(vph)):
            if not (0.35 < (vph[k][0] - vph[0][0]) / max(total_v, 1e-6) < 0.97):
                continue
            c1, *_ = dtw_map(vph[0][0] - pad, vph[k - 1][1] + pad, oph[0][0] - pad, g0 + pad)
            c2, *_ = dtw_map(vph[k][0] - pad, vph[-1][1] + pad, g1 - pad, oph[-1][1] + pad)
            c = (c1 + c2) / 2
            if best is None or c < best[0]:
                best = (c, k)
        c_one, *_ = dtw_map(vph[0][0] - pad, vph[-1][1] + pad, oph[0][0] - pad, oph[-1][1] + pad)
        if best is not None and np.isfinite(best[0]):
            c_split, k = best
            print(f'DTW cost: one piece {c_one:.3f}, split at voice {vph[k][0]:.1f}s -> song {g1:.1f}s: {c_split:.3f}')
            if c_split < c_one:
                segments = [
                    ((vph[0][0] - pad, vph[k - 1][1] + pad), (oph[0][0] - pad, g0 + pad)),
                    ((vph[k][0] - pad, vph[-1][1] + pad), (g1 - pad, oph[-1][1] + pad)),
                ]
    if not segments:
        segments = [((vph[0][0] - pad, vph[-1][1] + pad), (oph[0][0] - pad, oph[-1][1] + pad))]

    vt_all, st_all = [], []
    for (v0, v1), (o0, o1) in segments:
        _, vt, st = dtw_map(max(v0, 0), v1, max(o0, 0), o1)
        if vt is not None:
            vt_all.append(vt)
            st_all.append(st)
    vt = np.concatenate(vt_all)
    st = np.concatenate(st_all)

    grid = np.arange(0, len(voice) / SR, HOP / ASR)
    uv, idx = np.unique(vt, return_inverse=True)
    sm = np.bincount(idx, st) / np.bincount(idx)
    m = np.interp(grid, uv, sm)
    m = uniform_filter1d(m, size=max(1, int(0.6 * ASR / HOP)))
    m = np.maximum.accumulate(m)

    def to_song(t):
        return float(np.interp(t, grid, m))

    # ---------- reference pitch (cached) ----------
    print('pitch tracking (cached after first run)...')
    o_midi = dsp.f0_cached(oa, ASR, os.path.join(tmp_dir, 'orig_f0.npy'))
    v_midi = dsp.f0_cached(va, ASR, os.path.join(tmp_dir, 'voice_f0.npy'))
    tuning = float(librosa.estimate_tuning(y=librosa.resample(minus.mean(1), orig_sr=SR, target_sr=ASR), sr=ASR))
    print(f'minus tuning offset: {tuning * 100:+.0f} cents')

    align_mode = cfg['align']
    FOL = feats_local(oa, o_midi) if align_mode == 'local' else None
    FVL = feats_local(va, v_midi) if align_mode == 'local' else None

    def local_map(s, e, margin=0.8):
        T0, T1 = to_song(s), to_song(e)
        a0, a1 = int(s * ASR / HOP), int(e * ASR / HOP)
        b0 = max(0, int((T0 - margin) * ASR / HOP))
        b1 = min(FOL.shape[1], int((T1 + margin) * ASR / HOP))
        X, Y = FVL[:, a0:a1], FOL[:, b0:b1]
        if X.shape[1] < 8 or Y.shape[1] < X.shape[1] // 2 + 2:
            return None
        try:
            _, wp = librosa.sequence.dtw(X=X, Y=Y, metric='euclidean', subseq=True, step_sizes_sigma=STEPS)
        except librosa.util.exceptions.ParameterError:
            return None
        wp = wp[::-1]
        vt_, st_ = fr2t(wp[:, 0] + a0), fr2t(wp[:, 1] + b0)
        u_, i_ = np.unique(vt_, return_inverse=True)
        sm_ = np.bincount(i_, st_) / np.bincount(i_)
        g = np.arange(s, e, HOP / ASR)
        mm = np.maximum.accumulate(uniform_filter1d(np.interp(g, u_, sm_), size=max(3, int(0.2 * ASR / HOP))))
        ratio = (mm[-1] - mm[0]) / max(e - s, 1e-6)
        if not 0.6 <= ratio <= 1.6:
            return None
        return g, mm

    # ---------- 3. per-phrase pitch + time ----------
    overrides = [
        dict(o, **{'from': mmss(o['from']), 'to': mmss(o['to'])})
        for o in (json.load(open(shifts_path)) if os.path.exists(shifts_path) else [])
    ]
    out = np.zeros(song_len, dtype=np.float32)
    pre, post = 0.06, 0.25
    stats = {'cents_before': [], 'cents_after': [], 'ratios': [], 'placed': [], 'overrides': []}

    for n, (s, e) in enumerate(vph):
        s0 = max(0, s - pre)
        e0 = min(len(voice) / SR, e + post)
        seg = voice[int(s0 * SR):int(e0 * SR)]

        y22 = librosa.resample(seg, orig_sr=SR, target_sr=ASR)
        u = dsp.f0_pyin(y22, sr=ASR, fmin=70, fmax=1000)
        voiced = ~np.isnan(u)
        shift = np.zeros_like(u)
        if voiced.sum() > 5:
            u_f = np.where(voiced, u, np.interp(np.arange(len(u)), np.flatnonzero(voiced), u[voiced]))
            center = median_filter(u_f, size=13)
            tgt = np.round(center - tuning) + tuning
            for i in np.flatnonzero(voiced):
                j = int(to_song(s0 + fr2t(i)) * ASR / HOP)
                if 0 <= j < len(o_midi) and not np.isnan(o_midi[j]):
                    o = o_midi[j]
                    o += 12 * np.round((center[i] - o) / 12)
                    on = np.round(o - tuning) + tuning
                    if abs(on - center[i]) <= 1.0:
                        tgt[i] = on
            shift = np.where(voiced, (tgt - center) * cfg['pitch_strength'], 0.0)
            shift = np.clip(shift, -1.0, 1.0)
            if len(shift) > 9:
                shift = ss.filtfilt(*ss.butter(2, 8 / (ASR / HOP / 2)), shift)
            dev = lambda x: np.abs(((x - tuning + 0.5) % 1) - 0.5) * 100
            stats['cents_before'] += list(dev(center[voiced]))
            stats['cents_after'] += list(dev(center[voiced] + shift[voiced]))

        pin = os.path.join(tmp_dir, f'ph{n}_in.wav')
        pout = os.path.join(tmp_dir, f'ph{n}_p.wav')
        pm_file = os.path.join(tmp_dir, f'ph{n}_pm.txt')
        sf.write(pin, seg, SR)
        with open(pm_file, 'w') as f:
            for i, sh in enumerate(shift):
                f.write(f'{int(i * HOP * SR / ASR)} {sh:.4f}\n')
        subprocess.run(RB + ['-F', '--pitchmap', pm_file, pin, pout], check=True, capture_output=True)

        lm = local_map(s, e) if align_mode == 'local' else None
        ts = np.unique(np.r_[s, np.arange(s + 0.25, e - 0.12, 0.25), e])
        if lm is not None:
            T = np.interp(ts, *lm)
        else:
            T = np.array([to_song(t) for t in ts])
        total_ratio = (T[-1] - T[0]) / max(e - s, 1e-6)
        if not 0.6 <= total_ratio <= 1.6:
            T = T[0] + (ts - s)
            total_ratio = 1.0
        for _ in range(20):
            d = np.clip(np.diff(T) / np.maximum(np.diff(ts), 1e-6), 0.6, 1.6)
            T = np.r_[T[0], T[0] + np.cumsum(d * np.diff(ts))]
            T = T[0] + (T - T[0]) * total_ratio * (e - s) / max(T[-1] - T[0], 1e-6)

        if align_mode == 'shift':
            vf = np.arange(int(s * ASR / HOP), int(e * ASR / HOP))
            vm = v_midi[vf[vf < len(v_midi)]]
            st_v = np.interp(fr2t(vf[:len(vm)]), ts, T)

            def agree(L):
                j = np.round((st_v + L) * ASR / HOP).astype(int)
                ok = (j >= 0) & (j < len(o_midi))
                o = np.full(len(vm), np.nan)
                o[ok] = o_midi[j[ok]]
                k = ~np.isnan(o) & ~np.isnan(vm)
                if k.sum() < 15:
                    return -1
                a = vm[k] - np.median(vm[k])
                b = o[k] - np.median(o[k])
                return np.mean(np.abs(a - b) < 0.75) * k.mean()

            shifts_grid = np.arange(-0.4, 0.401, HOP / ASR * 2)
            sc = np.array([agree(L) for L in shifts_grid])
            base = agree(0.0)
            if sc.max() > base + 0.06 and base >= 0:
                T = T + shifts_grid[np.argmax(sc)]

        for ov in overrides:
            overlap = min(T[-1], ov['to']) - max(T[0], ov['from'])
            if overlap > 0.5 * min(T[-1] - T[0], ov['to'] - ov['from']):
                T = T + ov['shift_ms'] / 1000
                stats['overrides'].append(f"{ov['from']:.1f}s {ov['shift_ms']:+d} ms")
                break

        stats['ratios'].append(float(total_ratio))
        stats['placed'].append([n, round(s, 2), round(e, 2), round(float(T[0]), 2), round(float(T[-1]), 2)])

        src_t = np.r_[0, (ts - s0), e0 - s0]
        dst_t = np.r_[0, (T - T[0]) + (s - s0), (T[-1] - T[0]) + (s - s0) + (e0 - e)]
        out_len = dst_t[-1]
        tm_file = os.path.join(tmp_dir, f'ph{n}_tm.txt')
        ptime = os.path.join(tmp_dir, f'ph{n}_t.wav')
        with open(tm_file, 'w') as f:
            for a, b in zip(src_t, dst_t):
                f.write(f'{int(a * SR)} {int(b * SR)}\n')
        subprocess.run(RB + ['-M', tm_file, '-D', f'{out_len:.5f}', pout, ptime], check=True, capture_output=True)

        y_ph, _ = sf.read(ptime, always_2d=True)
        y_ph = y_ph.mean(1).astype(np.float32)
        fade_in = min(int(0.01 * SR), len(y_ph) // 4)
        fade_out = min(int(0.06 * SR), len(y_ph) // 4)
        if fade_in > 0:
            y_ph[:fade_in] *= np.linspace(0, 1, fade_in)
        if fade_out > 0:
            y_ph[-fade_out:] *= np.linspace(1, 0, fade_out)
        start = int((T[0] - (s - s0)) * SR)
        a, b = max(0, start), min(song_len, start + len(y_ph))
        if b > a:
            out[a:b] += y_ph[a - start:b - start]

    print(f"corrections applied: {stats['overrides']}")
    print(f'phrases placed: {len(vph)}, stretch ratios {np.min(stats["ratios"]):.2f}..{np.max(stats["ratios"]):.2f}')
    if stats['cents_before']:
        print(
            f'pitch error (median cents from note): before {np.median(stats["cents_before"]):.1f}, '
            f'after {np.median(stats["cents_after"]):.1f}'
        )
    aligned_raw_path = os.path.join(work_dir, 'vocal_aligned_raw.wav')
    sf.write(aligned_raw_path, out, SR)

    # ---------- 4. vocal processing ----------
    v = dsp.match_eq_fir(origv, out, SR) if cfg['match_eq'] else out
    v = dsp.vocal_tone_chain(v, SR, preset='mix')

    bpm = float(np.atleast_1d(librosa.beat.beat_track(
        y=librosa.resample(minus.mean(1), orig_sr=SR, target_sr=ASR), sr=ASR
    )[0])[0])
    if not np.isfinite(bpm) or bpm <= 0:
        bpm = 100.0
    while bpm > 120:
        bpm /= 2
    vocal_bus = dsp.vocal_space_bus(
        v,
        SR,
        reverb_db=cfg['reverb_db'],
        room=cfg['room'],
        delay_db=cfg['delay_db'],
        delay_sec=60.0 / bpm * 0.75,
        pre_delay_ms=30.0,
    )

    # ---------- 5. mix & master ----------
    meter = pyln.Meter(SR)
    origv_st, _ = sf.read(cfg['orig_vocal'], always_2d=True)
    ratio_db = meter.integrated_loudness(origv_st) - meter.integrated_loudness(minus)
    vl = meter.integrated_loudness(vocal_bus.T)
    ml = meter.integrated_loudness(minus)
    vocal_bus *= 10 ** ((ml + ratio_db + 0.5 - vl) / 20)

    env = np.abs(v)
    env = ss.lfilter([1 - 0.9995], [1, -0.9995], env)
    env = env / (np.percentile(env, 99) + 1e-9)
    duck = 10 ** (-1.5 * np.clip(env, 0, 1) / 20)
    mix = minus.T * duck[None, :minus.shape[0]] + vocal_bus[:, :minus.shape[0]]
    mix = Pedalboard([Compressor(threshold_db=-10, ratio=1.6, attack_ms=30, release_ms=200)])(
        mix.astype(np.float32), SR
    )
    mix = dsp.master_limiter(mix, SR, target_lufs=cfg['lufs'], lim_thresh_db=-3.0, ceiling_db=-1.2)

    out_base = cfg['out'] if os.path.dirname(cfg['out']) else os.path.join('output', cfg['out'])
    wav, mp3 = dsp.export_wav_mp3(mix, SR, out_base, title=os.path.basename(cfg['out']))
    stem_path = f'{out_base} - vokal stem.wav'
    sf.write(stem_path, vocal_bus.T / max(1e-9, float(np.abs(vocal_bus).max())) * 0.9, SR, subtype='PCM_24')

    print(f'bpm {bpm:.1f}, original vocal/minus balance {ratio_db:+.1f} dB')
    print(f'final: {meter.integrated_loudness(mix.T):.1f} LUFS, peak {np.abs(mix).max():.2f}')
    meta = {
        'voice': cfg['voice'],
        'origv': cfg['orig_vocal'],
        'minus': cfg['minus'],
        'aligned_vocal': aligned_raw_path,
        'shifts_file': shifts_path,
        'work_dir': work_dir,
        'bpm': bpm,
        'segments': segments,
        'n_phrases': len(vph),
        'placed': stats['placed'],
    }
    meta_path = os.path.join(work_dir, 'vocal_on_minus.json')
    with open(meta_path, 'w') as f:
        json.dump(meta, f, indent=1, default=float)
    # "last run" pointer so phrase_timing.py works without --project
    if os.path.abspath(meta_path) != os.path.abspath('work/vocal_on_minus.json'):
        os.makedirs('work', exist_ok=True)
        with open('work/vocal_on_minus.json', 'w') as f:
            json.dump(meta, f, indent=1, default=float)
    print('wrote', wav, mp3)


if __name__ == '__main__':
    main()
