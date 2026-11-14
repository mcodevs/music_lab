"""Separate a song or video into instrumental minus and vocal stems using Demucs htdemucs_ft.

Handles non-ASCII/Cyrillic filenames safely by converting to an ASCII 44.1 kHz stereo WAV first,
measures LUFS & vocal-to-minus balance, optionally runs a 2nd-pass bleed check (< -40 dB target),
and exports WAV/MP3 stems to output/. With --project it also assembles a ready cover project
(orig_vocals.wav, minus.wav and, with --voice, your Demucs-cleaned take as voice.wav).

Usage:
  .venv/bin/python -I scripts/separate_minus.py <input_media> [--name "Song Name"] [--check-bleed]
  .venv/bin/python -I scripts/separate_minus.py song.m4a --name "Song" --project work/song --voice my_take.m4a
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


def decode_wav(src, dst):
    """Decode any audio/video file to a 44.1 kHz stereo WAV with an ASCII-safe name for Demucs."""
    print(f'decoding -> {dst}')
    subprocess.run(
        ['ffmpeg', '-loglevel', 'error', '-y', '-i', src, '-vn', '-ar', str(SR), '-ac', '2', dst],
        check=True,
    )


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
    p.add_argument('--work-dir', default=None,
                   help='Demucs output base directory (default: work/separated)')
    p.add_argument('--four-stems', action='store_true',
                   help='Separate all 4 stems (drums, bass, other, vocals) instead of 2 stems')
    p.add_argument('--check-bleed', action='store_true',
                   help='Re-run Demucs on the separated minus to measure leftover vocal bleed (< -40 dB target)')
    p.add_argument('--device', default='mps',
                   help='Torch device for Demucs (default: mps; fallback: cpu)')
    p.add_argument('--project', default=None,
                   help='Also assemble a cover project folder: <project>/orig_vocals.wav + minus.wav '
                        '(+ voice.wav with --voice), ready for vocal_on_minus.py --project')
    p.add_argument('--voice', default=None,
                   help='Your raw a-cappella take (any format); cleaned of room noise with Demucs and '
                        'saved as <project>/voice.wav (requires --project)')
    args = p.parse_args()

    src_abs = os.path.abspath(args.input_media)
    if not os.path.exists(src_abs):
        sys.exit(f'Input media not found: {src_abs}')
    if args.voice and not args.project:
        p.error('--voice requires --project')
    voice_abs = os.path.abspath(args.voice) if args.voice else None
    if voice_abs and not os.path.exists(voice_abs):
        sys.exit(f'Voice take not found: {voice_abs}')
    # resolve user paths against the caller's cwd before switching to the project root
    work_dir = os.path.abspath(args.work_dir) if args.work_dir else os.path.join(ROOT, 'work', 'separated')
    project = os.path.abspath(args.project) if args.project else None

    os.chdir(ROOT)
    display_name = (args.name or os.path.splitext(os.path.basename(src_abs))[0]).replace('/', '-')
    slug = ascii_slug(display_name)

    os.makedirs('work', exist_ok=True)
    os.makedirs(work_dir, exist_ok=True)
    os.makedirs('output', exist_ok=True)

    src_wav = os.path.join('work', f'{slug}_src.wav')
    decode_wav(src_abs, src_wav)

    print(f'separating with htdemucs_ft (device={args.device}, four_stems={args.four_stems})...')
    run_demucs(src_wav, work_dir, device=args.device, four_stems=args.four_stems)

    stem_dir = os.path.join(work_dir, 'htdemucs_ft', slug + '_src')
    vocals_path = os.path.join(stem_dir, 'vocals.wav')
    minus_path = os.path.join(stem_dir, 'no_vocals.wav')

    if args.four_stems:
        # Always rebuild: a no_vocals.wav left by an earlier 2-stem run of the same song would
        # otherwise be used silently instead of the new 4-stem separation.
        parts = [sf.read(os.path.join(stem_dir, f'{s}.wav'), always_2d=True)[0]
                 for s in ('drums', 'bass', 'other')]
        sf.write(minus_path, np.sum(parts, axis=0).astype(np.float32), SR, subtype='FLOAT')

    orig_st, _ = sf.read(src_wav, always_2d=True)
    os.remove(src_wav)  # ~30-50 MB decode copy, no longer needed
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

    if not project:
        print(f'stems ready for cover:\n  --orig-vocal "{vocals_path}" --minus "{minus_path}"')
        return

    os.makedirs(project, exist_ok=True)
    shutil.copyfile(vocals_path, os.path.join(project, 'orig_vocals.wav'))
    shutil.copyfile(minus_path, os.path.join(project, 'minus.wav'))
    print(f'project {project}: orig_vocals.wav, minus.wav')
    if voice_abs:
        v_slug = f'{slug}_voice'
        v_wav = os.path.join('work', f'{v_slug}_src.wav')
        decode_wav(voice_abs, v_wav)
        print('cleaning your take with htdemucs_ft (room noise / bleed -> vocals stem)...')
        run_demucs(v_wav, work_dir, device=args.device, four_stems=False)
        os.remove(v_wav)
        shutil.copyfile(os.path.join(work_dir, 'htdemucs_ft', f'{v_slug}_src', 'vocals.wav'),
                        os.path.join(project, 'voice.wav'))
        print(f'project {project}: voice.wav (Demucs-cleaned)')
        rel = os.path.relpath(project, ROOT)
        print(f'next: .venv/bin/python -I scripts/vocal_on_minus.py --project "{rel}" --out "{display_name} (cover)"')
    else:
        print('add your take as voice.wav (or rerun with --voice <take>) before vocal_on_minus.py --project')


if __name__ == '__main__':
    main()
