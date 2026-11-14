"""Optimize video + audio (H.264 CRF 20, 30 fps CFR, 2-pass loudnorm -14 LUFS, +faststart)
and optionally replace audio with studio-polished voice (preserving .mov start_time lip-sync).

Lip-sync design: the video is encoded alone, the audio is processed to a wav (denoise latency
removed sample-exactly), then both are muxed at explicit positions taken from the source's
audio-vs-first-frame offset (mux_av). This is immune to ffmpeg's per-file start normalization,
the fps=30 start snap and AAC/loudnorm timestamp drift. Every output gets an A/V check.

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

# light clean-up for the optimized audio; afftdn adds 25 ms latency (removed, see filter_latency_s)
CLEAN_AF = 'highpass=f=70,afftdn=nf=-30:tn=1'


def probe_streams(path):
    """Probe video dimensions, fps, and video/audio start_time via ffprobe."""
    out = json.loads(subprocess.run(
        ['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', path],
        capture_output=True, text=True, check=True,
    ).stdout)
    streams = out.get('streams', [])
    v_stream = next((s for s in streams if s.get('codec_type') == 'video'), None)
    a_stream = next((s for s in streams if s.get('codec_type') == 'audio'), None)
    if v_stream is None:
        sys.exit(f'No video stream found in {path}')

    def _flt(val, default=0.0):
        try:
            return float(val)
        except (TypeError, ValueError):
            return default

    # Display size: iPhone portrait .mov stores landscape frames + a 90/270 degree rotation
    # (ffmpeg auto-rotates when decoding, so the outputs are portrait).
    w, h = int(v_stream.get('width', 0)), int(v_stream.get('height', 0))
    rot = [sd.get('rotation') for sd in v_stream.get('side_data_list', []) if 'rotation' in sd]
    rot = _flt(rot[0]) if rot else _flt(v_stream.get('tags', {}).get('rotate'), 0.0)
    if int(round(abs(rot))) % 180 == 90:
        w, h = h, w

    return {
        'width': w,
        'height': h,
        'rotation': rot,
        'fps': v_stream.get('avg_frame_rate', '30/1'),
        'v_start': _flt(v_stream.get('start_time'), 0.0),
        'has_audio': a_stream is not None,
        'a_start': _flt(a_stream.get('start_time'), 0.0) if a_stream else 0.0,
        'a_sr': int(_flt(a_stream.get('sample_rate'), 48000)) if a_stream else 48000,
        # file start = what ffmpeg subtracts from every stream when it reads the file (no -copyts)
        'start': _flt(out.get('format', {}).get('start_time'), 0.0),
    }


def measure_loudnorm_pass1(path, target_lufs=-14.0):
    """Run loudnorm pass 1 and return parsed JSON measurements, or None if unavailable."""
    af = f'{CLEAN_AF},loudnorm=I={target_lufs}:TP=-1.5:LRA=11:print_format=json'
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


def filter_latency_s(af, sr):
    """Delay (s) that the ffmpeg audio filter chain `af` adds, measured on a synthetic noise-burst
    signal at `sr`. afftdn delays its output by 25 ms (ffmpeg 9: 1102 samples @44.1k, 1200 @48k)
    while keeping the length, so uncompensated the optimized audio lags the picture by 25 ms."""
    rng = np.random.default_rng(0)
    n = int(1.5 * sr)
    x = np.zeros(n, np.float32)
    for k, t0 in enumerate((0.20, 0.55, 0.80, 1.10)):
        i0, ln = int(t0 * sr), int((0.08 + 0.04 * k) * sr)
        x[i0:i0 + ln] = 0.3 * rng.standard_normal(ln) * np.hanning(ln)
    with tempfile.TemporaryDirectory() as td:
        src, dst = os.path.join(td, 'in.wav'), os.path.join(td, 'out.wav')
        sf.write(src, x, sr)
        subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', src, '-af', af, '-ar', str(sr), dst], check=True)
        y, _ = sf.read(dst)
    m = min(len(x), len(y))
    corr = ss.correlate(y[:m], x[:m], mode='full', method='fft')[m - 1:m - 1 + int(0.2 * sr)]
    return int(np.argmax(corr)) / sr


def mux_av(video_only, wav, av_offset_s, out_path, a_bitrate='160k'):
    """Mux a video-only file with a wav so the wav's first sample plays `av_offset_s` after the
    first frame (negative = before). ffmpeg normalizes each input to start at 0, so the later one
    is pushed explicitly: video by -itsoffset, audio by a sample-exact adelay. Frames keep their
    1/30 s spacing; the video is stream-copied."""
    v_delay, a_delay = max(0.0, -av_offset_s), max(0.0, av_offset_s)
    cmd = ['ffmpeg', '-loglevel', 'error', '-y']
    if v_delay > 0:
        cmd += ['-itsoffset', f'{v_delay:.6f}']
    cmd += ['-i', video_only, '-i', wav, '-map', '0:v', '-map', '1:a', '-c:v', 'copy']
    n = round(a_delay * sf.info(wav).samplerate)
    if n > 0:
        cmd += ['-af', f'adelay={n}S:all=1']
    cmd += ['-c:a', 'aac', '-b:a', a_bitrate, '-movflags', '+faststart', out_path]
    subprocess.run(cmd, check=True)


def report_sync(label, orig_path, out_path):
    err, a_lag, v_shift, tol = check_av_sync(orig_path, out_path)
    status = 'OK' if abs(err) <= tol else f'WARNING: A/V error > {tol:.0f} ms'
    print(f'lip-sync ({label}): A/V error {err:+.1f} ms (audio lag {a_lag:+.1f} ms, '
          f'video start moved {v_shift:+.1f} ms) -> {status}')


def check_av_sync(orig_video, muxed_video, out_fps=30.0):
    """Lip-sync error of `muxed_video` relative to `orig_video`, in ms.

    Audio-only xcorr cannot see a shifted *video* start, so the error is audio_lag - video_shift:
    the audio lag from xcorr on each file's own timeline, minus how far the first frame moved on
    that timeline. Both are relative to the file start (min over streams), which ffmpeg subtracts
    on decode. Returns (error_ms, audio_lag_ms, video_shift_ms, tolerance_ms); tolerance = half an
    output frame + 1 ms.
    """
    audio_lag = check_sync_lag_ms(orig_video, muxed_video)
    o, m = probe_streams(orig_video), probe_streams(muxed_video)
    video_shift = ((m['v_start'] - m['start']) - (o['v_start'] - o['start'])) * 1000.0
    tolerance = 500.0 / out_fps + 1.0
    return audio_lag - video_shift, audio_lag, video_shift, tolerance


def check_sync_lag_ms(orig_video, muxed_video, duration_s=30):
    """Decode first `duration_s` s of both files' audio on the file timeline (PTS=0) and return
    the xcorr lag (ms) of the muxed audio vs the original audio."""
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
    # Amplitude envelope (rectified, zero-phase 40 Hz low-pass), NOT the raw rectified signal: the
    # latter keeps the pitch-period ripple, so after the polish EQ the xcorr can lock onto a
    # neighbouring pitch period (a 170 Hz voice measured -5.9 ms instead of 0; a low male voice
    # could jump ~15 ms). The envelope peak is unique; parabolic interpolation keeps it ~1-2 ms.
    sos = ss.butter(2, 40.0, fs=sr, output='sos')

    def _env(y):
        e = ss.sosfiltfilt(sos, np.abs(y[:n]))
        return e - e.mean()

    max_lag = int(0.5 * sr)
    corr = ss.correlate(_env(y2), _env(y1), mode='full', method='fft')
    mid = n - 1
    win = corr[mid - max_lag:mid + max_lag + 1]
    k = int(np.argmax(win))
    frac = 0.0
    if 0 < k < len(win) - 1:
        den = win[k - 1] - 2 * win[k] + win[k + 1]
        frac = 0.5 * (win[k - 1] - win[k + 1]) / den if den < 0 else 0.0
    return (k - max_lag + frac) * 1000.0 / sr


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
    p.add_argument('--delay-db', type=float, default=None,
                   help=f'Delay level in dB for --polish-voice (default: reverb_db - 8, i.e. {dsp.DEFAULT_DELAY_DB})')
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
    # Where the sound starts relative to the first frame. Both outputs are muxed at exactly this
    # offset (mux_av). Do NOT add atrim for audio-before-video: the offset already covers it.
    av_offset = info['a_start'] - info['v_start']
    rot_note = f' (rotated {info["rotation"]:+.0f} deg)' if info['rotation'] else ''
    print(
        f'probed {stem}: {info["width"]}x{info["height"]}{rot_note} fps={info["fps"]}, '
        f'v_start={info["v_start"]:.4f}s, a_start={info["a_start"]:.4f}s '
        f'(audio {av_offset * 1000:+.1f} ms vs first frame)'
    )

    with tempfile.TemporaryDirectory() as td:
        # 1a. video alone: H.264 CFR 30
        video_only = os.path.join(td, 'video.mp4')
        subprocess.run([
            'ffmpeg', '-loglevel', 'error', '-y', '-i', in_path, '-an', '-vf', 'fps=30',
            '-c:v', 'libx264', '-preset', 'slow', '-crf', str(args.crf), '-profile:v', 'high', '-g', '60',
            '-pix_fmt', 'yuv420p', '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709',
            '-movflags', '+faststart', video_only,
        ], check=True)

        # 1b. audio: clean-up + 2-pass loudnorm to a wav, denoise latency removed, then exact mux
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
            clean_wav = os.path.join(td, 'clean.wav')
            subprocess.run([
                'ffmpeg', '-loglevel', 'error', '-y', '-i', in_path, '-vn', '-af', f'{CLEAN_AF},{ln}',
                '-ar', str(info['a_sr']), '-ac', '2', '-c:a', 'pcm_f32le', clean_wav,
            ], check=True)
            y, sr = sf.read(clean_wav, always_2d=True)
            lat = round(filter_latency_s(CLEAN_AF, sr) * sr)
            if lat:
                y = np.concatenate([y[lat:], np.zeros((lat, y.shape[1]), y.dtype)])
                sf.write(clean_wav, y, sr, subtype='FLOAT')
            print(f'denoise latency {lat / sr * 1000:.1f} ms removed')
            mux_av(video_only, clean_wav, av_offset, opt_path, '160k')
        else:
            shutil.copyfile(video_only, opt_path)

        in_mb = os.path.getsize(in_path) / (1024 * 1024)
        opt_mb = os.path.getsize(opt_path) / (1024 * 1024)
        print(f'wrote {opt_path} ({opt_mb:.2f} MB vs {in_mb:.2f} MB input)')
        if info['has_audio']:
            report_sync('optimized', in_path, opt_path)

        if args.verify_ssim:
            ssim_val = measure_ssim(opt_path, in_path)
            if ssim_val is not None:
                print(f'SSIM vs original: {ssim_val:.4f}')

        # 2. Optional studio voice polish, muxed at the same offset
        if not args.polish_voice:
            return
        if not info['has_audio']:
            sys.exit('--polish-voice requested, but input video has no audio stream.')
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
            delay_db=args.delay_db if args.delay_db is not None else args.reverb_db - 8.0,
            target_lufs=-15.0,
            fix_cold=args.fix_cold,
        )
        print(f'diagnose: {diag["summary"]}')

        os.makedirs(os.path.join(ROOT, 'output'), exist_ok=True)
        pol_base = os.path.join(ROOT, 'output', f'{stem}_polished')
        pol_wav, pol_mp3 = dsp.export_wav_mp3(polished, voice_polish.SR, pol_base, title=f'{stem}_polished')
        print(f'polished audio: {pol_wav} / {pol_mp3}')

        mux_av(video_only, pol_wav, av_offset, fx_path, '192k')
        print(f'wrote {fx_path} (no -shortest)')
        report_sync('effects', in_path, fx_path)

if __name__ == '__main__':
    main()
