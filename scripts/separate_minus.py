"""Separate a song or video into instrumental minus and vocal stems using Demucs htdemucs_ft.

Handles non-ASCII/Cyrillic filenames safely by converting to an ASCII 44.1 kHz stereo WAV first,
measures LUFS & vocal-to-minus balance, optionally runs a 2nd-pass bleed check (< -40 dB target),
and exports WAV/MP3 stems to output/.

Usage:
  .venv/bin/python -I scripts/separate_minus.py <input_media> [--name "Song Name"] [--check-bleed]
"""
import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import numpy as np
import soundfile as sf
import pyloudnorm as pyln

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dsp

SR = 44100
_CYR_MAP = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo', 'ж': 'zh',
    'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o',
    'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u', 'ф': 'f', 'х': 'kh', 'ц': 'ts',
    'ч': 'ch', 'ш': 'sh', 'щ': 'shch', 'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu',
    'я': 'ya', 'қ': 'q', 'ғ': 'gh', 'ҳ': 'h', 'ў': 'o',
}


def ascii_slug(text):
    out = []
    for ch in text.lower():
        if ch in _CYR_MAP:
            out.append(_CYR_MAP[ch])
        elif ch.isascii() and ch.isalnum():
            out.append(ch)
        else:
            out.append('_')
    slug = re.sub(r'_+', '_', ''.join(out)).strip('_')
    if not slug:
        slug = 'track_' + hashlib.sha1(text.encode('utf-8')).hexdigest()[:6]
    return slug


def run_demucs(src_wav, out_dir, device='mps', four_stems=False):
    cmd = [sys.executable, '-I', '-m', 'demucs', '-n', 'htdemucs_ft']
    if not four_stems:
        cmd += ['--two-stems', 'vocals']
    cmd += ['-d', device, '--float32', '-o', out_dir, src_wav]
    subprocess.run(cmd, check=True)


def main():
    p = argparse.ArgumentParser(description='Separate a song or video into minus + vocal via Demucs.')
    p.add_argument('input_media', help='Input audio or video file (m4a, mp3, mp4, mov, ogg, wav, ...)')
    p.add_argument('--name', default=None,
                   help='Output display name (default: input filename stem)')
    p.add_argument('--work-dir', default='work/separated',
                   help='Demucs output base directory (default: work/separated)')
    p.add_argument('--four-stems', action='store_true',
                   help='Separate all 4 stems (drums, bass, other, vocals) instead of 2 stems')
    p.add_argument('--check-bleed', action='store_true',
                   help='Re-run Demucs on the separated minus to measure leftover vocal bleed (< -40 dB target)')
    p.add_argument('--device', default='mps',
                   help='Torch device for Demucs (default: mps; fallback: cpu)')
    args = p.parse_args()

    src_abs = os.path.abspath(args.input_media)
    if not os.path.exists(src_abs):
        sys.exit(f'Input media not found: {src_abs}')

    os.chdir(ROOT)
    display_name = args.name or os.path.splitext(os.path.basename(src_abs))[0]
    slug = ascii_slug(display_name)

    os.makedirs('work', exist_ok=True)
    os.makedirs(args.work_dir, exist_ok=True)
    os.makedirs('output', exist_ok=True)

    src_wav = os.path.join('work', f'{slug}_src.wav')
    print(f'decoding -> {src_wav}')
    subprocess.run(
        ['ffmpeg', '-loglevel', 'error', '-y', '-i', src_abs, '-vn', '-ar', str(SR), '-ac', '2', src_wav],
        check=True,
    )

    print(f'separating with htdemucs_ft (device={args.device}, four_stems={args.four_stems})...')
    run_demucs(src_wav, args.work_dir, device=args.device, four_stems=args.four_stems)

    stem_dir = os.path.join(args.work_dir, 'htdemucs_ft', slug + '_src')
    vocals_path = os.path.join(stem_dir, 'vocals.wav')
    minus_path = os.path.join(stem_dir, 'no_vocals.wav')

    if args.four_stems and not os.path.exists(minus_path):
        parts = [sf.read(os.path.join(stem_dir, f'{s}.wav'), always_2d=True)[0]
                 for s in ('drums', 'bass', 'other')]
        sf.write(minus_path, np.sum(parts, axis=0).astype(np.float32), SR, subtype='FLOAT')

    orig_st, _ = sf.read(src_wav, always_2d=True)
    minus_st, _ = sf.read(minus_path, always_2d=True)
    vocals_st, _ = sf.read(vocals_path, always_2d=True)

    meter = pyln.Meter(SR)
    l_orig = meter.integrated_loudness(orig_st)
    l_minus = meter.integrated_loudness(minus_st)
    l_voc = meter.integrated_loudness(vocals_st)
    print(f'LUFS: original {l_orig:.1f}, minus {l_minus:.1f}, vocal {l_voc:.1f} (balance {l_voc - l_minus:+.1f} dB)')

    if args.check_bleed:
        bleed_dir = os.path.join('work', f'_bleed_{slug}')
        print('checking vocal bleed in separated minus...')
        run_demucs(minus_path, bleed_dir, device=args.device, four_stems=False)
        bleed_v, _ = sf.read(os.path.join(bleed_dir, 'htdemucs_ft', 'no_vocals', 'vocals.wav'), always_2d=True)
        bleed_db = 10 * np.log10((np.mean(bleed_v ** 2) + 1e-12) / (np.mean(minus_st ** 2) + 1e-12))
        verdict = 'PASS (< -40 dB)' if bleed_db < -40.0 else 'WARN (> -40 dB; try --four-stems)'
        print(f'leftover vocal bleed in minus: {bleed_db:.1f} dB -> {verdict}')
        shutil.rmtree(bleed_dir, ignore_errors=True)

    out_minus = os.path.join('output', f'{display_name} (minus)')
    out_vocal = os.path.join('output', f'{display_name} (vokal)')
    m_wav, m_mp3 = dsp.export_wav_mp3(minus_st.T, SR, out_minus, title=f'{display_name} (minus)')
    v_mp3 = f'{out_vocal}.mp3'
    subprocess.run(
        ['ffmpeg', '-loglevel', 'error', '-y', '-i', vocals_path, '-c:a', 'libmp3lame', '-b:a', '320k',
         '-metadata', f'title={display_name} (vokal)', v_mp3],
        check=True,
    )
    print(f'exported:\n  minus: {m_wav} / {m_mp3}\n  vocal: {v_mp3}')
    print(f'stems ready for cover:\n  --orig-vocal "{vocals_path}" --minus "{minus_path}"')


if __name__ == '__main__':
    main()
