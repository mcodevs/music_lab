"""Quick global DTW inspection between a user vocal and an original vocal stem.

Usage: .venv/bin/python -I scripts/align_analysis.py <voice.wav> <orig_vocals.wav> [--out-wp work/wp.npy]
"""
import argparse
import os
import sys
import numpy as np
import librosa

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dsp

SR = 22050
HOP = 512


def main():
    p = argparse.ArgumentParser(description='Inspect global DTW path between user vocal and original vocal.')
    p.add_argument('voice', help='User vocal WAV path')
    p.add_argument('orig', help='Original vocal stem WAV path')
    p.add_argument('--out-wp', default=None, help='Output warping path .npy file (default: work/wp.npy)')
    args = p.parse_args()

    args.voice, args.orig = os.path.abspath(args.voice), os.path.abspath(args.orig)
    args.out_wp = os.path.abspath(args.out_wp) if args.out_wp else os.path.join(ROOT, 'work', 'wp.npy')
    os.chdir(ROOT)
    for lbl, path in [('voice', args.voice), ('orig', args.orig)]:
        if not os.path.exists(path):
            sys.exit(f'Missing {lbl} file: {path}')

    V = dsp.load_mono(args.voice, sr=SR)
    O = dsp.load_mono(args.orig, sr=SR)

    def feats(y):
        c = librosa.feature.chroma_cens(y=y, sr=SR, hop_length=HOP)
        r = librosa.feature.rms(y=y, hop_length=HOP)[0]
        r = (r > np.percentile(r, 40)).astype(float)
        # +1e-6: all-zero frames (digital silence) would make the cosine DTW cost NaN
        return np.vstack([c, 0.5 * r[None, :c.shape[1]]]) + 1e-6

    fv, fo = feats(V), feats(O)
    D, wp = librosa.sequence.dtw(
        X=fv, Y=fo, metric='cosine', subseq=True, step_sizes_sigma=np.array([[1, 1], [1, 2], [2, 1]])
    )
    wp = wp[::-1]
    tv = wp[:, 0] * HOP / SR
    to = wp[:, 1] * HOP / SR
    print('cost per step:', D[-1, :].min() / len(wp))
    print(f'voice 0 -> song {to[0]:.1f}s, voice end {tv[-1]:.1f}s -> song {to[-1]:.1f}s')

    iv = librosa.effects.split(O, top_db=35, hop_length=HOP)
    print('orig phrases:', [(round(a / SR, 1), round(b / SR, 1)) for a, b in iv if (b - a) / SR > 0.3])
    max_t = int(tv[-1])
    for t in range(0, max_t + 1, 10):
        i = np.searchsorted(tv, t)
        print(f'voice {t:4d}s -> song {to[min(i, len(to) - 1)]:6.1f}s')

    os.makedirs(os.path.dirname(os.path.abspath(args.out_wp)), exist_ok=True)
    np.save(args.out_wp, np.c_[tv, to])
    print('saved warping path:', args.out_wp)


if __name__ == '__main__':
    main()
