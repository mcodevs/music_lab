"""Music-video cover: a cappella performance (video + separate lav-mic memo) placed on a minus.

The singer keeps their own phrasing inside each line; only line starts are pulled onto the
song grid. Voice AND video are warped with the same time map, so lip sync is kept.

Pipeline:
  1. Optional cold/nasal cleanup (--fix-cold) and voice diagnostics.
  2. Line onsets (energy split) for voice and original vocal; 1:1 line mapping, checked by count.
  3. Minus: tempo matched to the singer (global fit) + transposed to the singer's key (Rubber Band R3).
  4. Voice: per-line pitch drift fix (a cappella sinks) + gentle note correction toward the
     transposed original melody; piecewise-linear time map onto the song grid.
  5. Vocal chain (EQ, de-ess, compression, dry-first plate + delay), mix, master to target LUFS.
  6. Video: same time map (frame remap), grade, slow push-in, vignette, grain, titles, fades.

Usage:
  .venv/bin/python -I scripts/clip_cover.py [config.json] [--fix-cold]
  .venv/bin/python -I scripts/clip_cover.py --init work/my_clip/clip.json --voice v.wav --orig-vocal ov.wav --minus m.wav --video v.mov
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import numpy as np
import soundfile as sf
import librosa
import scipy.signal as ss
import pyloudnorm as pyln
from scipy.ndimage import median_filter, uniform_filter1d
from pedalboard import Pedalboard, Compressor, Reverb
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dsp

SR, ASR, HOP = 44100, 22050, 256
RB = ['rubberband', '-q', '-3']

DEFAULT_CFG = dict(
    voice='',
    video='',
    voice_minus_video=0.0,
    origv='',
    minus='',
    orig_onsets=[],
    minus_shift=0,
    title='Cover',
    subtitle='cover',
    tmp='work/clip_tmp',
    target_lufs=-12.0,
    pitch_strength=0.6,
    intro=1.5,
    outro=3.0,
    reverb_db=dsp.DEFAULT_REVERB_DB,
    room=dsp.DEFAULT_ROOM,
    delay_db=None,  # None -> reverb_db - 8 (-26 dB with the default reverb)
    fix_cold=False,
)


def run(cmd):
    subprocess.run(cmd, check=True, capture_output=True)


def lines(y, top_db=30):
    iv = librosa.effects.split(y, top_db=top_db, frame_length=2048, hop_length=HOP) / ASR
    seg = []
    for a, b in iv:
        if seg and a - seg[-1][1] < 0.35:
            seg[-1][1] = b
        elif b - a > 0.25:
            seg.append([float(a), float(b)])
    return np.array(seg) if seg else np.zeros((0, 2))


def contour(m):
    """Key-free melody shape + voicing, for contour DTW."""
    med = np.nanmedian(m) if np.any(~np.isnan(m)) else 0.0
    x = np.nan_to_num(m - med)
    v_ = (~np.isnan(m)).astype(float)
    return np.vstack([x / 3 * v_, v_])


def _sync_envelope(x, sr, hop):
    """Log-energy envelope (200 Hz-4 kHz) with the slow trend removed: syllable on/offsets only,
    so a lav mic and a far, thin camera mic of the same performance correlate."""
    x = ss.sosfiltfilt(ss.butter(4, [200, 4000], btype='band', fs=sr, output='sos'), x)
    n = len(x) // hop
    e = np.log10(np.mean(x[:n * hop].reshape(n, hop) ** 2, axis=1) + 1e-10)
    e = e - uniform_filter1d(e, size=int(sr / hop))  # remove the 1 s trend (gain/room differences)
    return (e - e.mean()) / (e.std() + 1e-9)


def detect_voice_minus_video(voice, sr, video_path):
    """Seconds the separate voice recording starts before video frame 0 (`voice_minus_video`).

    Cross-correlates the voice with the video's own camera audio (even a poor 16 kHz track works).
    The camera audio is decoded on the file timeline, so the video stream's own start_time is
    added back. Returns (seconds, pearson_r, peak_ratio) or None when the video has no audio.
    """
    fs, hop = 16000, 80  # 5 ms envelope steps; parabolic refinement gets ~1 ms
    with tempfile.TemporaryDirectory() as td:
        cam_wav = os.path.join(td, 'cam.wav')
        r = subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', video_path, '-vn',
                            '-af', 'aresample=async=1:first_pts=0', '-ac', '1', '-ar', str(fs), cam_wav],
                           capture_output=True)
        if r.returncode != 0 or not os.path.exists(cam_wav) or os.path.getsize(cam_wav) < 1000:
            return None
        cam, _ = sf.read(cam_wav)
    vs = json.loads(subprocess.run(
        ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=start_time',
         '-of', 'json', video_path], capture_output=True, text=True, check=True).stdout)['streams'][0]
    v_start = float(vs.get('start_time', 0) or 0)

    ev = _sync_envelope(librosa.resample(voice, orig_sr=sr, target_sr=fs), fs, hop)
    ec = _sync_envelope(cam.astype(np.float32), fs, hop)
    c = ss.correlate(ev, ec, mode='full', method='fft')
    overlap = ss.correlate(np.ones(len(ev)), np.ones(len(ec)), mode='full', method='fft')
    min_ov = min(int(5.0 * fs / hop), len(ev) // 2, len(ec) // 2)  # need >= 5 s of common material
    c = np.where(overlap >= min_ov, c / np.maximum(overlap, 1), -np.inf)
    k = int(np.argmax(c))
    frac = 0.0
    if 0 < k < len(c) - 1 and np.isfinite(c[k - 1]) and np.isfinite(c[k + 1]):
        den = c[k - 1] - 2 * c[k] + c[k + 1]
        frac = 0.5 * (c[k - 1] - c[k + 1]) / den if den != 0 else 0.0
    lag = (k - (len(ec) - 1) + frac) * hop / fs  # voice time = camera file time + lag

    # confidence: correlation of the overlapping parts, and best peak vs best peak >= 0.5 s away
    i = k - (len(ec) - 1)
    a0, b0 = max(0, i), max(0, -i)
    n = min(len(ev) - a0, len(ec) - b0)
    pearson = float(np.corrcoef(ev[a0:a0 + n], ec[b0:b0 + n])[0, 1]) if n > 10 else 0.0
    far = c.copy()
    far[max(0, k - int(0.5 * fs / hop)):k + int(0.5 * fs / hop) + 1] = -np.inf
    second = float(np.max(far)) if np.isfinite(np.max(far)) else 0.0
    ratio = float(c[k] / second) if second > 0 else float('inf')
    return lag + v_start, pearson, ratio


def init_config(args):
    """Auto-detect line onsets & key shift via energy split + contour DTW, and save clip.json."""
    for lbl, path in [('voice', args.voice), ('orig_vocal', args.orig_vocal), ('minus', args.minus)]:
        if not path or not os.path.exists(path):
            sys.exit(f'--init requires existing --{lbl.replace("_", "-")} file (got: {path})')

    voice = dsp.load_mono(args.voice, sr=SR)
    origv = dsp.load_mono(args.orig_vocal, sr=SR)

    vmv = args.voice_minus_video
    if vmv is None and args.video:
        det = detect_voice_minus_video(voice, SR, args.video)
        if det is None:
            vmv = 0.0
            print('voice_minus_video: video has no audio track; set to 0.0 (measure it by hand)')
        else:
            vmv, r, ratio = det
            vmv = round(float(vmv), 3)
            weak = r < 0.3 or ratio < 1.3
            print(f'voice_minus_video: {vmv:+.3f} s auto-detected from the camera audio '
                  f'(match r={r:.2f}, peak ratio {ratio:.1f})'
                  + (' -- WEAK match, check lip sync or pass --voice-minus-video' if weak else ''))
    elif vmv is None:
        vmv = 0.0
    diag = dsp.diagnose_voice(voice, SR)
    print(f'diagnose: {diag["summary"]}')
    if args.fix_cold:
        voice = dsp.fix_cold_breathiness(voice, SR, reduce_db=dsp.DEFAULT_COLD_REDUCE_DB)
        voice = dsp.fix_nasal(voice, SR, strength=dsp.DEFAULT_DENASAL_STRENGTH)

    va = librosa.resample(voice, orig_sr=SR, target_sr=ASR)
    oa = librosa.resample(origv, orig_sr=SR, target_sr=ASR)
    vseg = lines(va)
    oseg = lines(oa)
    if len(vseg) == 0:
        sys.exit('No vocal lines detected in user voice.')

    v_midi = dsp.f0_pyin(va, sr=ASR, fmin=65, fmax=1000, hop_length=HOP)
    o_midi = dsp.f0_pyin(oa, sr=ASR, fmin=65, fmax=1000, hop_length=HOP)
    _, wp = librosa.sequence.dtw(
        contour(v_midi), contour(o_midi), subseq=True, step_sizes_sigma=np.array([[1, 1], [1, 2], [2, 1]])
    )
    wp = wp[::-1]
    vt = wp[:, 0] * HOP / ASR
    ot = wp[:, 1] * HOP / ASR

    d = v_midi[wp[:, 0]] - o_midi[wp[:, 1]]
    d = d[~np.isnan(d)]
    minus_shift = int(((int(round(float(np.median(d)))) + 6) % 12) - 6) if len(d) >= 10 else 0

    if len(oseg) == len(vseg):
        orig_onsets = [round(float(t), 2) for t in oseg[:, 0]]
    else:
        used = set()
        orig_onsets = []
        o_starts = oseg[:, 0] if len(oseg) else np.array([])
        for u in vseg[:, 0]:
            t_est = float(np.interp(u, vt, ot))
            picked = t_est
            if len(o_starts):
                idx = int(np.argmin(np.abs(o_starts - t_est)))
                if idx not in used and abs(o_starts[idx] - t_est) < 1.2:
                    if not orig_onsets or o_starts[idx] > orig_onsets[-1]:
                        picked = float(o_starts[idx])
                        used.add(idx)
            orig_onsets.append(round(picked, 2))

    slope = float(np.polyfit(orig_onsets, vseg[:, 0], 1)[0]) if len(orig_onsets) >= 2 else 1.0
    # Silence before the minus starts. Largest value (max 1.5 s) for which the clip still opens on
    # real footage: intro <= first voice line - (stretched) first original line - voice/video offset.
    lead_in = float(vseg[0, 0] - slope * orig_onsets[0] - vmv)
    intro = round(float(np.clip(lead_in, 0.0, 1.5)), 2)
    if lead_in < 0:
        print(f'note: the minus intro is {-lead_in:.1f} s longer than your lead-in; '
              f'the first video frame will be held for that long (intro=0)')
    out_dir = os.path.dirname(os.path.abspath(args.init))
    cfg = dict(DEFAULT_CFG)
    cfg.update({
        'voice': args.voice,
        'video': args.video or '',
        'voice_minus_video': vmv,
        'origv': args.orig_vocal,
        'minus': args.minus,
        'orig_onsets': orig_onsets,
        'minus_shift': minus_shift,
        'title': args.title or 'Cover',
        'subtitle': args.subtitle or 'cover',
        'tmp': args.tmp or os.path.join(out_dir, 'clip'),
        'intro': intro,
        'reverb_db': args.reverb_db if args.reverb_db is not None else dsp.DEFAULT_REVERB_DB,
        'room': args.room if args.room is not None else dsp.DEFAULT_ROOM,
        'delay_db': args.delay_db,
        # Only on explicit request: diagnostics are advisory and must not change a healthy voice.
        'fix_cold': bool(args.fix_cold),
    })
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.init, 'w') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print(
        f'wrote {args.init}: {len(orig_onsets)} lines (orig split {len(oseg)}), '
        f'est. tempo x{slope:.4f}, minus_shift {minus_shift:+d} st, intro {intro:.2f} s'
    )
    if not args.fix_cold and (diag['needs_cold_fix'] or diag['needs_denasal']):
        print('diagnostics suggest cold/nasal cleanup: listen first; if needed set "fix_cold": true '
              'in the config or pass --fix-cold')


def main():
    p = argparse.ArgumentParser(description='Create a lip-synced cover music video from a-cappella video + vocal.')
    p.add_argument('config', nargs='?', default=None, help='Path to clip.json config file')
    p.add_argument('--init', metavar='OUT_JSON', help='Auto-generate a clip.json template and exit')
    p.add_argument('--voice', help='Override user vocal path')
    p.add_argument('--orig-vocal', help='Override original vocal stem path')
    p.add_argument('--minus', help='Override minus WAV path')
    p.add_argument('--video', help='Override input video path')
    p.add_argument('--voice-minus-video', type=float, default=None,
                   help='Seconds the voice recording starts before the video (for --init; default: '
                        'auto-detected by cross-correlating with the camera audio)')
    p.add_argument('--title', help='Video title')
    p.add_argument('--subtitle', help='Video subtitle')
    p.add_argument('--tmp', help='Working temp directory')
    p.add_argument('--reverb-db', type=float, default=None, help=f'Reverb level dB (default: {dsp.DEFAULT_REVERB_DB})')
    p.add_argument('--room', type=float, default=None, help=f'Reverb room size (default: {dsp.DEFAULT_ROOM})')
    p.add_argument('--delay-db', type=float, default=None,
                   help=f'Delay level dB (default: reverb_db - 8, i.e. {dsp.DEFAULT_DELAY_DB})')
    p.add_argument('--fix-cold', action='store_true', help='Apply cold breathiness + denasal cleanup before alignment')
    args = p.parse_args()

    # Resolve user-given paths against the caller's cwd before switching to the project root.
    for attr in ('config', 'init', 'voice', 'orig_vocal', 'minus', 'video', 'tmp'):
        if getattr(args, attr):
            setattr(args, attr, os.path.abspath(getattr(args, attr)))
    os.chdir(ROOT)
    if args.init:
        init_config(args)
        return

    CFG = dict(DEFAULT_CFG)
    if args.config:
        if not os.path.exists(args.config):
            sys.exit(f'Config file not found: {args.config}')
        CFG.update(json.load(open(args.config)))
    for k, val in [('voice', args.voice), ('origv', args.orig_vocal), ('minus', args.minus),
                   ('video', args.video), ('title', args.title), ('subtitle', args.subtitle),
                   ('tmp', args.tmp), ('reverb_db', args.reverb_db), ('room', args.room), ('delay_db', args.delay_db)]:
        if val is not None:
            CFG[k] = val
    if args.fix_cold:
        CFG['fix_cold'] = True
    if CFG.get('delay_db') is None:
        CFG['delay_db'] = CFG['reverb_db'] - 8.0

    for lbl in ('voice', 'origv', 'minus', 'video'):
        if not CFG[lbl] or not os.path.exists(CFG[lbl]):
            sys.exit(
                f'Missing {lbl} file: {CFG[lbl]}\n'
                f'Hint: pass <config.json> or generate one with --init work/<name>/clip.json'
            )
    if not CFG['orig_onsets']:
        sys.exit('orig_onsets is empty in config; run with --init first or populate orig_onsets in clip.json.')

    TMP = CFG['tmp']
    os.makedirs(TMP, exist_ok=True)
    os.makedirs('output', exist_ok=True)
    OUT = f"output/{CFG['title']} (klip)"

    voice = dsp.load_mono(CFG['voice'], sr=SR)
    origv = dsp.load_mono(CFG['origv'], sr=SR)

    diag = dsp.diagnose_voice(voice, SR)
    print(f'diagnose: {diag["summary"]}')
    if CFG['fix_cold']:
        print('applying cold_fix + denasal...')
        voice = dsp.fix_cold_breathiness(voice, SR, reduce_db=dsp.DEFAULT_COLD_REDUCE_DB)
        voice = dsp.fix_nasal(voice, SR, strength=dsp.DEFAULT_DENASAL_STRENGTH)

    va = librosa.resample(voice, orig_sr=SR, target_sr=ASR)
    oa = librosa.resample(origv, orig_sr=SR, target_sr=ASR)

    # ---------- 1. lines ----------
    vseg = lines(va)
    U = vseg[:, 0]
    O = np.array(CFG['orig_onsets'], dtype=float)
    if len(U) != len(O):
        sys.exit(f'line count mismatch: voice {len(U)} vs original {len(O)} — fix orig_onsets / split')
    slope, icpt = np.polyfit(O, U, 1)
    print(f'{len(U)} lines; singer tempo vs original: x{slope:.4f}; residual std '
          f'{np.std(U - (icpt + slope * O)) * 1000:.0f} ms')

    tau_lines = CFG['intro'] + slope * O
    u_start = U[0] - tau_lines[0]
    vid_len = float(subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', CFG['video']],
        capture_output=True, text=True, check=True,
    ).stdout)
    u_end = min(vseg[-1, 1] + CFG['outro'], CFG['voice_minus_video'] + vid_len - 0.1, len(voice) / SR)
    if u_start < CFG['voice_minus_video']:
        # The minus intro is longer than the singer's lead-in: the clip starts before the recording.
        # Voice is padded with silence and the first video frame is held (see want_idx below).
        print(f'note: clip starts {CFG["voice_minus_video"] - u_start:.1f} s before the video; '
              f'holding the first frame (lower "intro" in the config to shorten it)')
    tau_end = tau_lines[-1] + (u_end - U[-1])
    anc_u = np.r_[u_start, U, u_end]
    anc_t = np.r_[0.0, tau_lines, tau_end]
    ratios = np.diff(anc_t) / np.diff(anc_u)
    print(f'line stretch ratios {ratios.min():.3f}..{ratios.max():.3f}; clip length {tau_end:.1f} s')

    # ---------- 2. minus: tempo + key ----------
    mwarp = f'{TMP}/minus_warp.wav'
    run(RB + ['-t', f'{slope:.5f}', '-p', str(CFG['minus_shift']), CFG['minus'], mwarp])
    minus, msr = sf.read(mwarp, always_2d=True)
    assert msr == SR
    tail_src = minus[-int(1.0 * SR):].T.astype(np.float32)
    tail = Pedalboard([Reverb(room_size=0.9, damping=0.5, wet_level=1.0, dry_level=0.0, width=1.0)])(
        np.concatenate([tail_src, np.zeros((2, int(5 * SR)), np.float32)], 1), SR
    )
    song_len = int(tau_end * SR) + int(0.5 * SR)
    mtrack = np.zeros((song_len, 2))
    m0 = int(CFG['intro'] * SR)
    n = min(len(minus), song_len - m0)
    mtrack[m0:m0 + n] = minus[:n]
    fo = int(0.08 * SR)
    mtrack[m0 + n - fo:m0 + n] *= np.linspace(1, 0.3, fo)[:, None]
    t0 = m0 + n - int(1.0 * SR)
    tl = min(tail.shape[1], song_len - t0)
    mtrack[t0:t0 + tl] += 0.55 * tail[:, :tl].T
    print(f'minus: x{slope:.4f} tempo, {CFG["minus_shift"]:+d} st, ends {(m0 + n) / SR:.1f} s (+ reverb tail)')

    # ---------- 3. voice: pitch ----------
    v_midi = dsp.f0_cached(va, ASR, f'{TMP}/voice_f0.npy', hop_length=HOP)
    o_midi = dsp.f0_cached(oa, ASR, f'{TMP}/orig_f0.npy', hop_length=HOP)
    REL = CFG['minus_shift'] - 12 * (CFG['minus_shift'] > 0)
    F = lambda t: int(t * ASR / HOP)

    o_at_v = np.full(len(v_midi), np.nan)
    line_shift = np.full(len(U), np.nan)
    line_iqr = np.zeros(len(U))
    for i, (a, b) in enumerate(vseg):
        vs = v_midi[F(a):F(b)]
        ob = F(max(0, O[i] - 0.4))
        os_ = o_midi[ob:F(O[i] + (b - a) + 0.6)]
        if np.isnan(vs).sum() > len(vs) - 20 or np.isnan(os_).sum() > len(os_) - 20:
            continue
        _, wp = librosa.sequence.dtw(contour(vs), contour(os_), subseq=True)
        wp = wp[::-1]
        u_, inv = np.unique(wp[:, 0], return_inverse=True)
        oj = np.round(np.bincount(inv, wp[:, 1]) / np.bincount(inv)).astype(int)
        o_at_v[F(a) + u_] = os_[oj] + REL
        d = vs[wp[:, 0]] - os_[wp[:, 1]]
        d = d[~np.isnan(d)]
        fold = d - 12 * np.round((d - np.median(d)) / 12)
        s_ = REL - np.median(fold)
        line_shift[i] = s_ - 12 * np.round(s_ / 12)
        line_iqr[i] = np.subtract(*np.percentile(fold, [75, 25]))
    if np.all(np.isnan(line_shift)):
        print('warning: no line had enough pitched frames for drift measurement; per-line fix disabled')
        line_shift[:] = 0.0
    line_shift = np.where(np.isnan(line_shift), np.nanmedian(line_shift), line_shift)
    print('per-line pitch fix (st):', ' '.join(f'{x:+.1f}' for x in line_shift))
    print('   contour spread (IQR):', ' '.join(f'{x:.1f}' for x in line_iqr))

    frames = np.arange(len(v_midi))
    ft = frames * HOP / ASR
    edges = np.r_[0, (vseg[1:, 0] + vseg[:-1, 1]) / 2]
    base = line_shift[np.clip(np.searchsorted(edges, ft, side='right') - 1, 0, len(U) - 1)]
    voiced = ~np.isnan(v_midi)
    u_f = np.where(voiced, v_midi, np.interp(frames, np.flatnonzero(voiced), v_midi[voiced]))
    center = median_filter(u_f, size=13) + base
    tuning = float(librosa.estimate_tuning(y=librosa.resample(mtrack.mean(1)[m0:m0 + 30 * SR], orig_sr=SR, target_sr=ASR), sr=ASR))
    tgt = np.round(center - tuning) + tuning
    near = ~np.isnan(o_at_v)
    om = o_at_v + 12 * np.round((center - o_at_v) / 12)
    use_o = near & (np.abs(np.round(om - tuning) + tuning - center) <= 1.0)
    tgt[use_o] = (np.round(om - tuning) + tuning)[use_o]
    fine = np.clip((tgt - center) * CFG['pitch_strength'], -1, 1) * voiced
    shift = base + fine
    shift = ss.filtfilt(*ss.butter(2, 8 / (ASR / HOP / 2)), shift)
    dev = lambda x: np.abs(((x - tuning + 0.5) % 1) - 0.5) * 100
    print(
        f'pitch error (cents from note): before {np.median(dev(center[voiced] - base[voiced] + np.median(line_shift))):.0f}, '
        f'after {np.median(dev(center[voiced] + fine[voiced])):.0f}'
    )

    a0, a1 = int(u_start * SR), int(u_end * SR)
    vin = f'{TMP}/voice_cut.wav'
    # u_start can be negative (clip starts before the recording): pad with silence instead of
    # letting a negative index wrap around to the end of the take.
    sf.write(vin, np.r_[np.zeros(max(0, -a0), np.float32), voice[max(0, a0):a1]], SR)
    pm = f'{TMP}/pitchmap.txt'
    with open(pm, 'w') as f:
        for i in range(int(u_start * ASR / HOP), int(u_end * ASR / HOP)):
            f.write(f'{int(i * HOP * SR / ASR) - a0} {shift[int(np.clip(i, 0, len(shift) - 1))]:.4f}\n')
    vp = f'{TMP}/voice_pitched.wav'
    run(RB + ['-F', '--pitchmap', pm, vin, vp])
    tm = f'{TMP}/timemap.txt'
    with open(tm, 'w') as f:
        for a, b in zip(anc_u - u_start, anc_t):
            f.write(f'{int(a * SR)} {int(b * SR)}\n')
    vt = f'{TMP}/voice_timed.wav'
    run(RB + ['-F', '-M', tm, '-D', f'{tau_end:.5f}', vp, vt])
    v = dsp.load_mono(vt, sr=SR)
    v = np.pad(v, (0, max(0, song_len - len(v))))[:song_len]

    # ---------- 4. vocal chain + mix ----------
    v = dsp.vocal_tone_chain(v, SR, preset='memo')
    bpm = CFG.get('bpm') or float(np.atleast_1d(librosa.beat.beat_track(
        y=librosa.resample(dsp.load_mono(CFG['minus'], sr=SR), orig_sr=SR, target_sr=ASR), sr=ASR
    )[0])[0]) / slope
    if not np.isfinite(bpm) or bpm <= 0:
        bpm = 100.0
    while bpm > 120:
        bpm /= 2

    vbus = dsp.vocal_space_bus(
        v,
        SR,
        reverb_db=CFG['reverb_db'],
        room=CFG['room'],
        delay_db=CFG['delay_db'],
        delay_sec=60.0 / bpm * 0.75,
        pre_delay_ms=30.0,
    )
    meter = pyln.Meter(SR)
    ov_st, _ = sf.read(CFG['origv'], always_2d=True)
    om_st, _ = sf.read(CFG['minus'], always_2d=True)
    ratio_db = meter.integrated_loudness(ov_st) - meter.integrated_loudness(om_st)
    VOCAL_DB = min(ratio_db, 3.0)
    vbus *= 10 ** ((meter.integrated_loudness(mtrack[m0:m0 + len(minus)]) + VOCAL_DB - meter.integrated_loudness(vbus.T)) / 20)
    env = ss.lfilter([1 - 0.9995], [1, -0.9995], np.abs(v))
    env /= np.percentile(env, 99) + 1e-9
    mix = mtrack.T * (10 ** (-1.5 * np.clip(env, 0, 1) / 20))[None] + vbus
    mix = Pedalboard([Compressor(threshold_db=-10, ratio=1.6, attack_ms=30, release_ms=200)])(
        mix.astype(np.float32), SR
    )
    mix = dsp.master_limiter(mix, SR, target_lufs=CFG['target_lufs'], lim_thresh_db=-3.0, ceiling_db=-1.2)
    mix = mix[:, :int(tau_end * SR)]
    fade = int(1.2 * SR)
    mix[:, -fade:] *= np.linspace(1, 0, fade) ** 2

    dsp.export_wav_mp3(mix, SR, OUT, title=f"{CFG['title']} ({CFG['subtitle']})")
    sf.write(f'{TMP}/vocal_stem.wav', vbus.T / max(1e-9, np.abs(vbus).max()) * 0.9, SR, subtype='PCM_24')
    print(
        f'bpm {bpm:.1f}; vocal {VOCAL_DB:+.1f} dB over minus (original {ratio_db:+.1f}); '
        f'final {meter.integrated_loudness(mix.T):.1f} LUFS, peak {20 * np.log10(np.abs(mix).max()):.1f} dBFS'
    )

    # ---------- 5. video ----------
    W, H, FPS = 1280, 720, 30
    vs = json.loads(subprocess.run(
        ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_streams', '-of', 'json', CFG['video']],
        capture_output=True, text=True, check=True,
    ).stdout)['streams'][0]
    vw, vh = int(vs['width']), int(vs['height'])
    # ffmpeg auto-rotates on decode (iPhone portrait .mov), so raw frames come out with swapped size
    rot = [sd.get('rotation') for sd in vs.get('side_data_list', []) if 'rotation' in sd]
    rot = float(rot[0]) if rot else float(vs.get('tags', {}).get('rotate', 0) or 0)
    if int(round(abs(rot))) % 180 == 90:
        vw, vh = vh, vw
    num, den = map(int, vs.get('avg_frame_rate', '30/1').split('/'))
    src_fps = num / den if den else 30.0
    if vh > vw:  # portrait source -> portrait clip instead of squashing it into 16:9
        W, H = 720, 1280
    # largest centred crop of the source with the output aspect ratio (no stretching)
    base_cw, base_ch = (vw, vw * H / W) if vw / vh <= W / H else (vh * W / H, vh)
    n_out = int(tau_end * FPS)
    want = np.interp(np.arange(n_out) / FPS, anc_t, anc_u) - CFG['voice_minus_video']
    want_idx = np.clip(np.round(want * src_fps).astype(int), 0, None)

    def text_png(path, lines_, sizes, fonts, align='left', pad=60, y0=None, shadow=True):
        img = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        y = y0
        for txt, sz, fp in zip(lines_, sizes, fonts):
            f = ImageFont.truetype(fp, sz)
            w = d.textlength(txt, font=f)
            x = pad if align == 'left' else (W - w) / 2
            d.text((x, y), txt, font=f, fill=(255, 248, 238, 255))
            y += int(sz * 1.25)
        if shadow:
            sh = img.split()[3].filter(ImageFilter.GaussianBlur(6))
            base_ = Image.new('RGBA', (W, H), (0, 0, 0, 0))
            base_.putalpha(sh.point(lambda px: int(px * 0.55)))
            img = Image.alpha_composite(base_, img)
        img.save(path)

    SERIF = '/System/Library/Fonts/Supplemental/Didot.ttc'
    SANS = '/System/Library/Fonts/Avenir Next.ttc'
    text_png(f'{TMP}/title.png', [CFG['title'], CFG['subtitle'].upper()], [58, 22], [SERIF, SANS], y0=H - 190)
    text_png(f'{TMP}/end.png', [CFG['title'], CFG['subtitle'].upper()], [64, 24], [SERIF, SANS], align='center', y0=H // 2 - 60)

    T_IN0, T_IN1 = 0.6, CFG['intro'] + 4.5
    T_END0 = tau_end - 3.2
    ZOOM = 0.07
    vf = (
        f"[0:v]eq=contrast=1.07:saturation=1.06:gamma=0.97,colortemperature=temperature=5600:mix=0.35,"
        "colorbalance=rs=0.03:bs=-0.03:rh=0.02:bh=-0.02,"
        "vignette=angle=PI/4.6,noise=alls=2:allf=t,format=yuv420p[base];"
        f"[1:v]format=rgba,fade=in:st={T_IN0}:d=0.8:alpha=1,fade=out:st={T_IN1 - 0.8}:d=0.8:alpha=1[ti];"
        f"[2:v]format=rgba,fade=in:st={T_END0}:d=1.0:alpha=1[en];"
        f"[base][ti]overlay=0:0:enable='between(t,{T_IN0},{T_IN1})'[b1];"
        f"[b1]fade=out:st={T_END0 + 0.2}:d=1.4:color=0x0b0907[b2];"
        f"[b2][en]overlay=0:0:enable='gte(t,{T_END0})',fade=in:st=0:d=0.9[v]"
    )
    enc = subprocess.Popen(
        ['ffmpeg', '-loglevel', 'error', '-y',
         '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
         '-loop', '1', '-framerate', str(FPS), '-t', f'{tau_end:.3f}', '-i', f'{TMP}/title.png',
         '-loop', '1', '-framerate', str(FPS), '-t', f'{tau_end:.3f}', '-i', f'{TMP}/end.png',
         '-i', f'{OUT}.wav',
         '-filter_complex', vf, '-map', '[v]', '-map', '3:a',
         '-c:v', 'libx264', '-preset', 'slow', '-crf', '19', '-tune', 'grain', '-maxrate', '12M', '-bufsize', '24M', '-pix_fmt', 'yuv420p',
         '-c:a', 'aac', '-b:a', '320k', '-movflags', '+faststart', '-shortest', f'{OUT}.mp4'],
        stdin=subprocess.PIPE,
    )
    dec = subprocess.Popen(
        ['ffmpeg', '-loglevel', 'error', '-i', CFG['video'], '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
        stdout=subprocess.PIPE,
    )
    fsz = vw * vh * 3
    cur_idx, cur, img = -1, None, None
    for k, j in enumerate(want_idx):
        while cur_idx < j:
            buf = dec.stdout.read(fsz)
            if len(buf) < fsz:
                break
            cur, cur_idx = buf, cur_idx + 1
            img = None
        if cur is None:
            enc.kill()
            dec.kill()
            sys.exit(f'could not decode any frame from {CFG["video"]}')
        if img is None:
            img = Image.frombuffer('RGB', (vw, vh), cur, 'raw', 'RGB', 0, 1)
        z = 1 + ZOOM * k / n_out
        cw, ch = base_cw / z, base_ch / z
        x0, y0 = (vw - cw) / 2, (vh - ch) * 0.42
        enc.stdin.write(img.resize((W, H), Image.BICUBIC, box=(x0, y0, x0 + cw, y0 + ch)).tobytes())
    enc.stdin.close()
    rc = enc.wait()
    dec.kill()
    dec.wait()
    if rc != 0:
        sys.exit(f'ffmpeg video encode failed (exit code {rc}); {OUT}.mp4 is incomplete')
    print(f'video: {n_out} frames, source frames {want_idx[0]}..{want_idx[-1]}; wrote {OUT}.mp4')
    json.dump(
        dict(slope=slope, line_shift=line_shift.tolist(), ratios=ratios.tolist(), bpm=bpm,
             u_start=u_start, u_end=u_end, tau_end=tau_end, vocal_db=VOCAL_DB),
        open(f'{TMP}/report.json', 'w'),
        indent=1,
    )


if __name__ == '__main__':
    main()
