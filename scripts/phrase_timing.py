"""Per-phrase timing check of placed user vocal vs original singer using two independent cues:
onset envelopes (consonants / word starts) and pitch contours (note changes).

Prints a per-phrase lag table; with --suggest writes phrase_shifts.json where BOTH cues agree;
with --plot saves alignment_check.png, reports chroma similarity, and measures bleed in any >10 s
instrumental break automatically.

Usage:
  .venv/bin/python -I scripts/phrase_timing.py [--project work/<name>] [--suggest] [--plot]
  .venv/bin/python -I scripts/phrase_timing.py --aligned <raw.wav> --orig <orig_vocals.wav>
"""
import argparse
import json
import os
import sys
import numpy as np
import librosa
import scipy.signal as ss

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dsp

SR = 22050
HOP = 256


def _resolve_paths(args):
    # With --project only that project's metadata is used; without it, the "last run" pointer
    # work/vocal_on_minus.json written by vocal_on_minus.py.
    work_dir = args.project.rstrip('/') if args.project else 'work'
    meta = {}
    meta_path = os.path.join(work_dir, 'vocal_on_minus.json')
    if os.path.exists(meta_path):
        with open(meta_path) as f:
            meta = json.load(f)
    if not args.project and meta.get('work_dir'):
        work_dir = meta['work_dir']

    aligned = args.aligned or (
        os.path.join(work_dir, 'vocal_aligned_raw.wav')
        if args.project and os.path.exists(os.path.join(work_dir, 'vocal_aligned_raw.wav'))
        else meta.get('aligned_vocal')
    )
    orig = args.orig or (
        os.path.join(work_dir, 'orig_vocals.wav')
        if args.project and os.path.exists(os.path.join(work_dir, 'orig_vocals.wav'))
        else meta.get('origv')
    )
    shifts_file = meta.get('shifts_file') or os.path.join(work_dir, 'phrase_shifts.json')
    if args.project:
        shifts_file = os.path.join(work_dir, 'phrase_shifts.json')
    # content-hashed by dsp.f0_cached, so a cache from another song is never reused
    cache_orig = os.path.join(work_dir, 'tmp', 'orig_f0.npy')
    plot_path = os.path.join(work_dir, 'alignment_check.png')
    return aligned, orig, shifts_file, cache_orig, plot_path


def main(argv=None):
    p = argparse.ArgumentParser(description='Evaluate per-phrase timing vs original vocal.')
    p.add_argument('--project', help='Project directory under work/ (reads vocal_on_minus.json)')
    p.add_argument('--aligned', help='Aligned raw vocal WAV path')
    p.add_argument('--orig', help='Original singer vocal WAV path')
    p.add_argument('--suggest', action='store_true',
                   help='Write agreed onset+pitch corrections to phrase_shifts.json')
    p.add_argument('--plot', action='store_true',
                   help='Save alignment_check.png and report chroma similarity + instrumental break bleed')
    args = p.parse_args(argv)

    for attr in ('project', 'aligned', 'orig'):
        if getattr(args, attr):
            setattr(args, attr, os.path.abspath(getattr(args, attr)))
    os.chdir(ROOT)
    aligned_path, orig_path, shifts_path, cache_orig, plot_path = _resolve_paths(args)
    for label, path in [('aligned vocal', aligned_path), ('original vocal', orig_path)]:
        if not path or not os.path.exists(path):
            sys.exit(
                f'Missing {label} file: {path}\n'
                f'Hint: run scripts/vocal_on_minus.py first or pass --project / --aligned / --orig.'
            )

    mine = dsp.load_mono(aligned_path, sr=SR)
    orig = dsp.load_mono(orig_path, sr=SR)
    n = min(len(mine), len(orig))
    mine, orig = mine[:n], orig[:n]

    oe = librosa.onset.onset_strength(y=orig, sr=SR, hop_length=HOP)
    me = librosa.onset.onset_strength(y=mine, sr=SR, hop_length=HOP)
    om = dsp.f0_cached(orig, SR, cache_orig, fmin=70, fmax=1000, hop_length=HOP)
    mm = dsp.f0_pyin(mine, sr=SR, fmin=70, fmax=1000, hop_length=HOP)
    L = min(len(om), len(mm), len(oe), len(me))
    om, mm, oe, me = om[:L], mm[:L], oe[:L], me[:L]

    def onset_lag(fa, fb, w):
        o = oe[fa:fb] - oe[fa:fb].mean()
        m = me[fa:fb] - me[fa:fb].mean()
        c = ss.correlate(m, o, mode='full')
        k = len(o) - 1
        c = c[k - w:k + w + 1]
        return (np.argmax(c) - w) * HOP / SR * 1000, c.max() / (np.linalg.norm(o) * np.linalg.norm(m) + 1e-9)

    def pitch_lag(fa, fb, w):
        best = (None, -1.0)
        for lag in range(-w, w + 1):
            if fa + lag < 0 or fb + lag > L:
                continue
            o = om[fa:fb]
            m = mm[fa + lag:fb + lag]
            ok = ~np.isnan(o) & ~np.isnan(m)
            if ok.sum() < 20:
                continue
            a = o[ok] - np.median(o[ok])
            b = m[ok] - np.median(m[ok])
            sc = float(np.mean(np.abs(a - b) < 0.75) * ok.mean())
            if sc > best[1]:
                best = (lag * HOP / SR * 1000, sc)
        return best

    w = int(0.5 * SR / HOP)
    splits = librosa.effects.split(orig, top_db=35, hop_length=HOP)
    rows = []
    sims = []
    ref_db = 10 * np.log10(np.mean(mine[mine != 0] ** 2) + 1e-12) if np.any(mine != 0) else -120.0

    for a, b in splits:
        if (b - a) / SR < 1.0:
            continue
        fa, fb = a // HOP, b // HOP
        my_db = 10 * np.log10(np.mean(mine[a:b] ** 2) + 1e-12)
        if my_db < ref_db - 12:
            print(f'{a / SR // 60:.0f}:{a / SR % 60:04.1f}  — my vocal absent here, skipped')
            continue
        ol, oc = onset_lag(fa, fb, w)
        pl, pc = pitch_lag(fa, fb, w)
        rows.append(dict(
            start=a / SR, end=b / SR,
            onset_ms=round(ol), onset_conf=round(float(oc), 2),
            pitch_ms=None if pl is None else round(pl), pitch_conf=round(float(pc), 2),
        ))
        if args.plot:
            co = librosa.feature.chroma_cens(y=orig[a:b], sr=SR)
            cm = librosa.feature.chroma_cens(y=mine[a:b], sr=SR)
            sims.append(float(np.mean(np.sum(co * cm, 0) / (np.linalg.norm(co, axis=0) * np.linalg.norm(cm, axis=0) + 1e-9))))

    fmt = lambda t: f'{int(t // 60)}:{t % 60:04.1f}'
    print(f'{"phrase":>15}  onset_ms  pitch_ms  -> shift_ms')
    sugg = []
    for r in rows:
        shift = None
        ol, pl = r['onset_ms'], r['pitch_ms']
        if pl is not None and abs(ol) >= 100 and np.sign(ol) == np.sign(pl) and abs(ol - pl) <= 150:
            shift = -round((ol + pl) / 2)
            sugg.append(dict(**{'from': fmt(r['start']), 'to': fmt(r['end'])}, shift_ms=shift, reason='auto: onset+pitch agree'))
        print(f'{fmt(r["start"]):>7}-{fmt(r["end"]):<7}  {ol:8d}  {str(pl):>8}  -> {"" if shift is None else shift}')

    if rows:
        ok = lambda x: np.mean(np.abs(np.array(x)) <= 60) * 100
        print(f'onset: median |lag| {np.median([abs(r["onset_ms"]) for r in rows]):.0f} ms, within 60 ms {ok([r["onset_ms"] for r in rows]):.0f}%')
        pls = [r['pitch_ms'] for r in rows if r['pitch_ms'] is not None]
        if pls:
            print(f'pitch: median |lag| {np.median(np.abs(pls)):.0f} ms, within 60 ms {ok(pls):.0f}%')

    if args.plot:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt

        if sims:
            print(f'melody (chroma) similarity per phrase: median {np.median(sims):.2f}, min {np.min(sims):.2f}')
        # Automatically detect instrumental breaks > 10 s between original phrases
        gaps = [(splits[i][1] / SR, splits[i + 1][0] / SR)
                for i in range(len(splits) - 1) if (splits[i + 1][0] - splits[i][1]) / SR > 10.0]
        db = lambda x: 10 * np.log10(np.mean(x ** 2) + 1e-12)
        for g0, g1 in gaps:
            seg = mine[int((g0 + 0.5) * SR):int((g1 - 0.5) * SR)]
            if len(seg) > SR:
                print(f'my vocal level in break {g0:.1f}-{g1:.1f}s: {db(seg) - db(mine):.1f} dB vs average')

        fig, ax = plt.subplots(3, 1, figsize=(16, 6), sharex=True)
        for a_, (y, lbl) in zip(ax[:2], [(orig, 'original vocal'), (mine, 'my vocal (aligned)')]):
            r = librosa.feature.rms(y=y, hop_length=HOP)[0]
            a_.fill_between(np.arange(len(r)) * HOP / SR, r, color='C0' if 'orig' in lbl else 'C1')
            a_.set_ylabel(lbl, fontsize=8)
        ro = librosa.feature.rms(y=orig, hop_length=HOP)[0]
        rm = librosa.feature.rms(y=mine, hop_length=HOP)[0]
        ax[2].plot(np.arange(len(ro)) * HOP / SR, ro / max(ro.max(), 1e-9), lw=0.6, label='original')
        ax[2].plot(np.arange(len(rm)) * HOP / SR, rm / max(rm.max(), 1e-9), lw=0.6, label='mine')
        ax[2].legend()
        ax[2].set_xlabel('song time, s')
        plt.tight_layout()
        os.makedirs(os.path.dirname(os.path.abspath(plot_path)), exist_ok=True)
        plt.savefig(plot_path, dpi=80)
        print('saved plot:', plot_path)

    if args.suggest:
        old = json.load(open(shifts_path)) if os.path.exists(shifts_path) else []
        manual = [x for x in old if not x.get('reason', '').startswith('auto')]
        os.makedirs(os.path.dirname(os.path.abspath(shifts_path)), exist_ok=True)
        json.dump(manual + sugg, open(shifts_path, 'w'), ensure_ascii=False, indent=1)
        print(f'wrote {len(sugg)} auto suggestions (+{len(manual)} manual kept) to {shifts_path}')


if __name__ == '__main__':
    main()
