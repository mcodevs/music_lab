"""Polish a solo voice recording (phone memo): diagnostics, optional cold/nasal fix, EQ,
de-ess, compression, dry-first plate reverb + delay, stereo double, and loudness mastering.

Usage:
  .venv/bin/python -I scripts/voice_polish.py <input audio> <output name> [reverb_db=-18] [room=0.5]
  .venv/bin/python -I scripts/voice_polish.py <input audio> --diagnose
  .venv/bin/python -I scripts/voice_polish.py <input audio> <output name> --fix-cold
"""
import argparse
import os
import sys
import numpy as np
import pyloudnorm as pyln

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dsp

SR = 48000


def polish_voice(
    y,
    sr=SR,
    reverb_db=dsp.DEFAULT_REVERB_DB,
    room=dsp.DEFAULT_ROOM,
    delay_db=None,
    target_lufs=-15.0,
    fix_cold=False,
    cold_db=dsp.DEFAULT_COLD_REDUCE_DB,
    denasal_strength=dsp.DEFAULT_DENASAL_STRENGTH,
    diag=None,
):
    """Run diagnostics (unless `diag` is given) and full solo vocal polish chain on mono audio `y`."""
    if diag is None:
        diag = dsp.diagnose_voice(y, sr)
    if fix_cold:
        y = dsp.fix_cold_breathiness(y, sr, reduce_db=cold_db)
        y = dsp.fix_nasal(y, sr, strength=denasal_strength)
    y = dsp.vocal_tone_chain(y, sr, preset='memo')
    out = dsp.vocal_space_bus(
        y,
        sr,
        reverb_db=reverb_db,
        room=room,
        delay_db=delay_db if delay_db is not None else reverb_db - 8.0,
        delay_sec=0.375,
        pre_delay_ms=35.0,
        stereo_double_db=-18.0,
    )
    m = dsp.master_limiter(out, sr, target_lufs=target_lufs, lim_thresh_db=-1.5, ceiling_db=-1.0)
    return m, diag


def main():
    p = argparse.ArgumentParser(
        description='Polish a solo voice recording (EQ, de-ess, compression, reverb/delay, mastering).'
    )
    p.add_argument('src', help='Input audio file (wav, m4a, ogg, mp3, ...)')
    p.add_argument('name', nargs='?', default=None,
                   help='Output name without extension (written to output/<name>.wav/.mp3 unless path given)')
    p.add_argument('pos_reverb_db', metavar='reverb_db', nargs='?', type=float, default=None,
                   help=f'Positional reverb level in dB (default: {dsp.DEFAULT_REVERB_DB})')
    p.add_argument('pos_room', metavar='room', nargs='?', type=float, default=None,
                   help=f'Positional reverb room size 0..1 (default: {dsp.DEFAULT_ROOM})')
    p.add_argument('--reverb-db', type=float, default=None,
                   help=f'Reverb level in dB (default: {dsp.DEFAULT_REVERB_DB})')
    p.add_argument('--room', type=float, default=None,
                   help=f'Reverb room size 0..1 (default: {dsp.DEFAULT_ROOM})')
    p.add_argument('--delay-db', type=float, default=None,
                   help='Delay level in dB (default: reverb_db - 8.0, i.e. -26.0 dB)')
    p.add_argument('--lufs', type=float, default=-15.0,
                   help='Target integrated loudness in LUFS (default: -15.0)')
    p.add_argument('--fix-cold', action='store_true',
                   help='Run cold breathiness + denasal chain before EQ/effects')
    p.add_argument('--cold-db', type=float, default=dsp.DEFAULT_COLD_REDUCE_DB,
                   help=f'Cold breathiness reduction dB (default: {dsp.DEFAULT_COLD_REDUCE_DB})')
    p.add_argument('--denasal', type=float, default=dsp.DEFAULT_DENASAL_STRENGTH,
                   help=f'Denasalization strength 0..1 (default: {dsp.DEFAULT_DENASAL_STRENGTH})')
    p.add_argument('--diagnose', action='store_true',
                   help='Print detailed voice diagnostics (may omit output name to only inspect)')
    args = p.parse_args()

    if not args.diagnose and not args.name:
        p.error('output <name> is required unless --diagnose is specified')

    src_path = os.path.abspath(args.src)
    out_base = None
    if args.name:
        out_base = os.path.abspath(args.name) if os.path.dirname(args.name) else os.path.join(ROOT, 'output', args.name)

    reverb_db = args.reverb_db if args.reverb_db is not None else (
        args.pos_reverb_db if args.pos_reverb_db is not None else dsp.DEFAULT_REVERB_DB
    )
    room = args.room if args.room is not None else (
        args.pos_room if args.pos_room is not None else dsp.DEFAULT_ROOM
    )
    delay_db = args.delay_db if args.delay_db is not None else reverb_db - 8.0

    y = dsp.load_mono(src_path, sr=SR)
    diag = dsp.diagnose_voice(y, SR)
    print(f'diagnose: {diag["summary"]}')

    if args.diagnose:
        for k, v in diag.items():
            if k != 'summary':
                print(f'  {k}: {v}')
        if not args.name:
            return

    m, _ = polish_voice(
        y,
        sr=SR,
        reverb_db=reverb_db,
        room=room,
        delay_db=delay_db,
        target_lufs=args.lufs,
        fix_cold=args.fix_cold,
        cold_db=args.cold_db,
        denasal_strength=args.denasal,
        diag=diag,
    )
    wav, mp3 = dsp.export_wav_mp3(m, SR, out_base, title=os.path.basename(args.name))
    meter = pyln.Meter(SR)
    lufs = meter.integrated_loudness(m.T)
    peak_db = 20 * np.log10(max(1e-9, float(np.abs(m).max())))
    print(
        f'{lufs:.1f} LUFS, peak {peak_db:.1f} dBFS '
        f'(reverb {reverb_db:+.1f} dB, room {room:.2f}, delay {delay_db:+.1f} dB) -> {wav} {mp3}'
    )


if __name__ == '__main__':
    main()
