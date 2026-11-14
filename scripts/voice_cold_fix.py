"""Reduce cold / hoarse breathiness in a solo voice: attenuate inter-harmonic noise in voiced frames.

Tracks f0 (pyin), builds a harmonic comb mask (keeps energy near k*f0, lowers what is between harmonics),
applies it below ~5.5 kHz only on voiced frames. Unvoiced parts (consonants, sibilance, breaths) stay untouched.

usage: .venv/bin/python -I scripts/voice_cold_fix.py <in.wav> <out.wav> [reduce_db=7]
"""
import argparse
import os
import sys
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dsp

SR = 48000


def main():
    p = argparse.ArgumentParser(description='Attenuate inter-harmonic breathiness in a cold/hoarse voice.')
    p.add_argument('src', help='Input audio file')
    p.add_argument('dst', help='Output WAV file')
    p.add_argument('reduce_db', nargs='?', type=float, default=dsp.DEFAULT_COLD_REDUCE_DB,
                   help=f'Inter-harmonic attenuation in dB (default: {dsp.DEFAULT_COLD_REDUCE_DB})')
    args = p.parse_args()

    y = dsp.load_mono(args.src, sr=SR)
    out = dsp.fix_cold_breathiness(y, SR, reduce_db=args.reduce_db)
    parent = os.path.dirname(os.path.abspath(args.dst))
    if parent:
        os.makedirs(parent, exist_ok=True)
    sf.write(args.dst, out, SR, subtype='FLOAT')
    print(f'wrote {args.dst} (reduce_db={args.reduce_db:.1f})')


if __name__ == '__main__':
    main()
