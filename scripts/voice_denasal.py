"""Tame a congested / nasal ("ming'illagan") singing voice.

A cold blocks the nose: the voice gets boxy (~400-600 Hz) and honky (~1-1.8 kHz) resonances
and loses the 2-3.5 kHz "ring". Uses dynamic 1-octave resonance suppression (350-1900 Hz)
plus gentle static EQ, preserving overall loudness.
Run AFTER scripts/voice_cold_fix.py (breathiness) and before any effects.

usage: .venv/bin/python -I scripts/voice_denasal.py <in.wav> <out.wav> [strength=0.7]
"""
import argparse
import os
import sys
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dsp


def main():
    p = argparse.ArgumentParser(description='Tame congested/nasal resonances in a singing voice.')
    p.add_argument('src', help='Input audio file')
    p.add_argument('dst', help='Output WAV file')
    p.add_argument('strength', nargs='?', type=float, default=dsp.DEFAULT_DENASAL_STRENGTH,
                   help=f'Denasalization strength 0..1 (default: {dsp.DEFAULT_DENASAL_STRENGTH})')
    args = p.parse_args()

    y, sr = sf.read(args.src, always_2d=True)
    y = y.mean(1).astype('float32')
    out, stats = dsp.fix_nasal(y, sr, strength=args.strength, return_stats=True)
    parent = os.path.dirname(os.path.abspath(args.dst))
    if parent:
        os.makedirs(parent, exist_ok=True)
    sf.write(args.dst, out, sr, subtype='FLOAT')
    print(
        f'avg reduction in 350-1900 Hz on active frames: {stats["avg_red_db"]:.1f} dB, '
        f'max {stats["max_red_db"]:.1f} dB -> {args.dst}'
    )


if __name__ == '__main__':
    main()
