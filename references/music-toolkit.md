---
name: music-toolkit
description: music_lab'dagi o'rnatilgan audio vositalar (.venv Python 3.11, Demucs, Rubber Band, basic-pitch, FluidR3_GM) va ularning tuzoqlari
metadata:
  type: reference
---

# Musiqa vositalari (2026-11-13 o'rnatilgan)

Loyiha skill'i: `.claude/skills/voice-to-music/SKILL.md` — ish tartibi o'sha yerda.

**Muhit:** `.venv` (uv, **Python 3.11** — 3.14 da basic-pitch/torch yo'q). Ro'yxat: `requirements.txt`.
Skriptlar har doim `.venv/bin/python -I scripts/...` bilan ishga tushiriladi.

| Vosita | Vazifa |
|---|---|
| ffmpeg | ogg/opus/m4a → wav, mp3 320k eksport |
| librosa | tempo, tonallik, pyin (f0), onset, DTW |
| basic-pitch (ONNX) | ovoz → MIDI |
| pretty_midi + fluidsynth + `soundfonts/FluidR3_GM.sf2` | MIDI → audio |
| pedalboard | EQ, kompressor, reverb, delay, limiter |
| pyloudnorm | LUFS |
| **Demucs 4.1** | qo'shiq → minus + vokal ([[minus-ajratish]]) |
| **Rubber Band 4.0** (brew) | vaqtni cho'zish (`-M` timemap), o'zgaruvchan pitch (`--pitchmap`), formant saqlash (`-F`), R3 dvigatel (`-3`) |

## Tuzoqlar (har biri amalda uchradi)

- **basic-pitch:** standart model yo'li CoreML — ishlamaydi. ONNX modelni aniq ber:
  `glob('.venv/.../basic_pitch/saved_models/icassp_2022/*.onnx')`. Yana `setuptools<81`
  (resampy `pkg_resources` so'raydi) va `scikit-learn<=1.5.1` kerak.
- **pedalboard `Limiter`** (JUCE) o'zi make-up gain qo'shadi: −12 LUFS ga normallab, keyin
  limiter qo'ysang −9 LUFS chiqadi. Kirish gain'ini iteratsiya bilan sozlash kerak
  ([[vocal-on-minus]] da shunday qilingan).
- **Rubber Band `--pitchmap`** realtime rejimni yoqadi, lekin o'lchandi: kechikish 0.2 ms,
  uzunlik o'zgarmaydi — xavfsiz.
- **SoundFont:** fluidsynth bilan faqat kichik sinov sf2 keladi. FluidR3_GM (142 MB) rasmiy
  Debian paketidan olingan (`fluid-soundfont-gm_3.1-6_all.deb`). Git'da yo'q; qayta olish uchun
  `sh scripts/get_soundfont.sh` (SHA-256 `74594e8f…1cb0`), batafsil `soundfonts/README.md` ([[git-repo]]).
- **Internet:** iPhone hotspot orqali (172.20.10.x) torch ~12 daqiqa, Demucs modellari
  ~0.2 MB/s yuklandi. Katta yuklashni foydalanuvchiga oldindan ayt.
- Obsidian vault = `~/my_projects`, ya'ni `music_lab/` papkasining o'zi.

Bog'liq: [[voice-polish-chain]], [[vocal-on-minus]], [[minus-ajratish]]
