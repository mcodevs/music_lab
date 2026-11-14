"""Optimize video + audio (H.264 CRF 20, 30 fps CFR, 2-pass loudnorm -14 LUFS, +faststart)
and optionally replace audio with studio-polished voice (preserving .mov start_time lip-sync).

Usage:
  .venv/bin/python -I scripts/video_optimize.py <input_video> [--polish-voice] [--fix-cold] [--verify-ssim]
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import numpy as np
import soundfile as sf
import scipy.signal as ss

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dsp
import voice_polish


def probe_streams(path):
    """Probe video dimensions, fps, and video/audio start_time via ffprobe."""
    out = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', path],
        capture_output=True, text=True, check=True,
    ).stdout
    streams = json.loads(out).get('streams', [])
    v_stream = next((s for s in streams if s.get('codec_type') == 'video'), None)
    a_stream = next((s for s in streams if s.get('codec_type') == 'audio'), None)
    if v_stream is None:
        sys.exit(f'No video stream found in {path}')

    def _flt(val, default=0.0):
        try:
            return float(val)
        except (TypeError, ValueError):
            return default

    return {
        'width': int(v_stream.get('width', 0)),
        'height': int(v_stream.get('height', 0)),
        'fps': v_stream.get('avg_frame_rate', '30/1'),
        'v_start': _flt(v_stream.get('start_time'), 0.0),
        'has_audio': a_stream is not None,
        'a_start': _flt(a_stream.get('start_time'), 0.0) if a_stream else 0.0,
    }


def measure_loudnorm_pass1(path, target_lufs=-14.0):
    """Run loudnorm pass 1 and return parsed JSON measurements, or None if unavailable."""
    af = f'highpass=f=70,afftdn=nf=-30:tn=1,loudnorm=I={target_lufs}:TP=-1.5:LRA=11:print_format=json'
    res = subprocess.run(
        ['ffmpeg', '-hide_banner', '-y', '-i', path, '-vn', '-af', af, '-f', 'null', '-'],
        capture_output=True, text=True, check=True,
    )
    matches = re.findall(r'\{[^{}]*"input_i"[^{}]*\}', res.stderr, re.DOTALL)
    if not matches:
        return None
    stats = json.loads(matches[-1])
    for key in ('input_i', 'input_tp', 'input_lra', 'input_thresh', 'target_offset'):
        try:
            if not np.isfinite(float(stats[key])):
                return None
        except (KeyError, TypeError, ValueError):
            return None
    return stats


def measure_ssim(opt_path, orig_path):
    """Measure average SSIM between optimized CFR video and original video."""
    cmd = [
        'ffmpeg', '-hide_banner', '-i', opt_path, '-i', orig_path,
        '-lavfi', '[0:v]setpts=PTS-STARTPTS[a];[1:v]fps=30,setpts=PTS-STARTPTS[b];[a][b]ssim',
        '-f', 'null', '-',
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    m = re.search(r'All:([0-9.]+)', res.stderr)
    return float(m.group(1)) if m else None


def check_sync_lag_ms(orig_video, muxed_video, duration_s=30):
    """Decode first `duration_s` s of both videos from PTS=0 and estimate xcorr lag (ms)."""
    sr = 16000
    with tempfile.TemporaryDirectory() as td:
        w1 = os.path.join(td, 'orig.wav')
        w2 = os.path.join(td, 'mux.wav')
        for src, dst in [(orig_video, w1), (muxed_video, w2)]:
            subprocess.run(
                ['ffmpeg', '-loglevel', 'error', '-y', '-t', str(duration_s), '-i', src, '-vn',
                 '-af', 'aresample=async=1:first_pts=0', '-ac', '1', '-ar', str(sr), dst],
                check=True,
            )
        y1, _ = sf.read(w1)
        y2, _ = sf.read(w2)
    n = min(len(y1), len(y2))
    if n < sr // 4:
        return 0.0
    # Use RMS/amplitude envelope at 1 kHz resolution for robustness to EQ/reverb changes
    y1 = np.abs(y1[:n]) - np.mean(np.abs(y1[:n]))
    y2 = np.abs(y2[:n]) - np.mean(np.abs(y2[:n]))
    max_lag = int(0.5 * sr)
    corr = ss.correlate(y2, y1, mode='full')
    mid = len(y1) - 1
    win = corr[mid - max_lag:mid + max_lag + 1]
    lag_samples = int(np.argmax(win)) - max_lag
    return lag_samples * 1000.0 / sr


def main():
    p = argparse.ArgumentParser(description='Optimize video + audio and optionally apply studio voice polish.')
    p.add_argument('input_video', help='Input video file (.mov, .mp4, ...)')
    p.add_argument('--out-dir', default=None,
                   help='Output directory for _optimized.mp4 / _effects.mp4 (default: alongside input video)')
    p.add_argument('--crf', type=int, default=20, help='x264 CRF quality (default: 20)')
    p.add_argument('--lufs', type=float, default=-14.0, help='Target audio loudness for _optimized (default: -14.0)')
    p.add_argument('--polish-voice', action='store_true',
                   help='Also create <stem>_effects.mp4 using voice_polish (and output/<stem>_polished.wav/.mp3)')
    p.add_argument('--fix-cold', action='store_true',
                   help='Apply cold breathiness + denasal cleanup when polishing voice')
    p.add_argument('--reverb-db', type=float, default=dsp.DEFAULT_REVERB_DB,
                   help=f'Reverb level in dB for --polish-voice (default: {dsp.DEFAULT_REVERB_DB})')
    p.add_argument('--room', type=float, default=dsp.DEFAULT_ROOM,
                   help=f'Reverb room size for --polish-voice (default: {dsp.DEFAULT_ROOM})')
    p.add_argument('--verify-ssim', action='store_true', help='Measure SSIM of _optimized.mp4 vs input')
    args = p.parse_args()

    in_path = os.path.abspath(args.input_video)
    if not os.path.exists(in_path):
        sys.exit(f'Input video not found: {in_path}')

    out_dir = os.path.abspath(args.out_dir) if args.out_dir else os.path.dirname(in_path)
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(in_path))[0]
    opt_path = os.path.join(out_dir, f'{stem}_optimized.mp4')
    fx_path = os.path.join(out_dir, f'{stem}_effects.mp4')

    info = probe_streams(in_path)
    offset_s = max(0.0, info['a_start'] - info['v_start'])
    offset_ms = round(offset_s * 1000.0)
    print(
        f'probed {stem}: {info["width"]}x{info["height"]} fps={info["fps"]}, '
        f'v_start={info["v_start"]:.4f}s, a_start={info["a_start"]:.4f}s (offset {offset_ms} ms)'
    )

    # 1. Optimized video + 2-pass loudnorm audio
    cmd = [
        'ffmpeg', '-loglevel', 'error', '-y', '-i', in_path,
        '-vf', 'fps=30',
        '-c:v', 'libx264', '-preset', 'slow', '-crf', str(args.crf), '-profile:v', 'high', '-g', '60',
        '-pix_fmt', 'yuv420p', '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709',
    ]
    if info['has_audio']:
        stats = measure_loudnorm_pass1(in_path, target_lufs=args.lufs)
        if stats is not None:
            ln = (
                f"loudnorm=I={args.lufs}:TP=-1.5:LRA=11:"
                f"measured_I={stats['input_i']}:measured_TP={stats['input_tp']}:"
                f"measured_LRA={stats['input_lra']}:measured_thresh={stats['input_thresh']}:"
                f"offset={stats['target_offset']}:linear=true"
            )
        else:
            ln = f'loudnorm=I={args.lufs}:TP=-1.5:LRA=11'
        cmd += ['-af', f'highpass=f=70,afftdn=nf=-30:tn=1,{ln}', '-c:a', 'aac', '-b:a', '160k', '-ac', '2']
    else:
        cmd += ['-an']
    cmd += ['-movflags', '+faststart', opt_path]
    subprocess.run(cmd, check=True)

    in_mb = os.path.getsize(in_path) / (1024 * 1024)
    opt_mb = os.path.getsize(opt_path) / (1024 * 1024)
    print(f'wrote {opt_path} ({opt_mb:.2f} MB vs {in_mb:.2f} MB input)')

    if args.verify_ssim:
        ssim_val = measure_ssim(opt_path, in_path)
        if ssim_val is not None:
            print(f'SSIM vs original: {ssim_val:.4f}')

    # 2. Optional studio voice polish + sync-preserving mux
    if args.polish_voice:
        if not info['has_audio']:
            sys.exit('--polish-voice requested, but input video has no audio stream.')
        with tempfile.TemporaryDirectory() as td:
            raw_wav = os.path.join(td, 'voice_raw.wav')
            subprocess.run(
                ['ffmpeg', '-loglevel', 'error', '-y', '-i', in_path, '-vn', '-ac', '1',
                 '-ar', str(voice_polish.SR), raw_wav],
                check=True,
            )
            y = dsp.load_mono(raw_wav, sr=voice_polish.SR)

        polished, diag = voice_polish.polish_voice(
            y,
            sr=voice_polish.SR,
            reverb_db=args.reverb_db,
            room=args.room,
            delay_db=args.reverb_db - 8.0,
            target_lufs=-15.0,
            fix_cold=args.fix_cold,
        )
        print(f'diagnose: {diag["summary"]}')

        os.makedirs(os.path.join(ROOT, 'output'), exist_ok=True)
        pol_base = os.path.join(ROOT, 'output', f'{stem}_polished')
        pol_wav, pol_mp3 = dsp.export_wav_mp3(polished, voice_polish.SR, pol_base, title=f'{stem}_polished')
        print(f'polished audio: {pol_wav} / {pol_mp3}')

        mux_cmd = [
            'ffmpeg', '-loglevel', 'error', '-y',
            '-i', opt_path, '-i', pol_wav,
            '-map', '0:v', '-map', '1:a',
            '-c:v', 'copy',
        ]
        if offset_ms > 2:
            mux_cmd += ['-af', f'adelay={offset_ms}|{offset_ms}']
        mux_cmd += ['-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', fx_path]
        subprocess.run(mux_cmd, check=True)
        print(f'wrote {fx_path} (adelay={offset_ms} ms, no -shortest)')

        lag_ms = check_sync_lag_ms(in_path, fx_path)
        status = 'OK' if abs(lag_ms) <= 5.0 else 'WARNING: sync lag > 5 ms'
        print(f'lip-sync check (xcorr): {lag_ms:+.2f} ms ({status})')


if __name__ == '__main__':
    main()
