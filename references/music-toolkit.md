---
name: music-toolkit
description: music_lab'dagi audio vositalar (.venv Python 3.11, Demucs, Rubber Band, basic-pitch, FluidR3_GM), tuzoqlari, melody_to_song / selftest; 2026-11-14 review'da topilgan ma'lum kamchiliklar (requirements.txt to'liq emas, minor tonallik akkordlari)
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

## `scripts/melody_to_song.py` (2026-11-14)
Xirgoyi (`hum.m4a "Nom"`) qo'shiqqa shu bosqichlarda aylanadi:
1. basic-pitch notalarni ajratadi; ishlamasa, pYIN zaxira sifatida ishlatiladi.
2. Monofonik tozalash.
3. Beat grid kuylovchiga ergashadi.
4. Krumhansl bo'yicha tonallik aniqlanadi.
5. Viterbi har taktga diatonik akkord tanlaydi.
6. Aranjirovka: akkord, pad, bas va GM baraban.
7. fluidsynth bilan render, ustiga ovoz qo'yiladi, −14 LUFS.

Sintetik xirgoyida: 22/22 nota, Am. Ishlashi ~5 s.

**Ma'lum kamchiliklar (2026-11-14 review, tuzatilmagan, kodda tasdiqlangan):**
- **Minor tonallik:** melodiya natural minorga "snap" qilinadi, akkordlar esa shu snap qilingan notalardan tanlanadi. Natijada kuylangan G# (Am) G ga aylanadi, V akkord hech qachon yutmaydi va ovoz bilan to'qnashadi. Yechim: akkordni snap qilinmagan notalardan tanlash va harmonik minorga snap qilish.
- **`--intro-bars` amalda ishlamaydi:** `build_midi` doim 0-taktni intro deb oladi. Grid faqat 8 beat oldinga boradi, shuning uchun 2 dan katta qiymat 2 ga tushib qoladi.
- **MIDI taktlarga to'g'ri kelmaydi:** .mid bitta doimiy tempo bilan yoziladi, taktlar esa kuylovchining suzuvchi beatiga ergashadi. Bosh qismdagi jimlik ham kesilmaydi.
- **`clean_notes`:** ustma-ust tushgan notalar qolishi mumkin. Oldingi nota tashlanganda undan avvalgisi bilan qayta tekshirilmaydi.
- **Noto'g'ri yorliq:** pYIN zaxirasi ishlaganda ham "basic-pitch" deb chop etiladi. Selftest pYIN bilan ham o'tadi, ya'ni basic-pitch buzilsa sezilmaydi.
- **pYIN takroriy notalar:** bir xil balandlikdagi ketma-ket notalarni bitta notaga qo'shib yuboradi.
- **Voicing:** ovozni akkordga moslash halqasi o'lik kod — barcha variantlar bir xil chiqadi.

## Tuzoqlar (har biri amalda uchradi)
- **basic-pitch:**
  - Standart model yo'li CoreML va u ishlamaydi. ONNX modelni aniq ko'rsat: `glob('.venv/.../basic_pitch/saved_models/icassp_2022/*.onnx')`.
  - Qo'shimcha talablar: `setuptools<81` va `scikit-learn<=1.5.1`.
- **pedalboard `Limiter`** o'zidan make-up gain qo'shadi. Shuning uchun kirish gain'ini iteratsiya bilan sozla (`dsp.master_limiter`).
- **Rubber Band `--pitchmap`:** kechikishi 0.2 ms, uzunlikni o'zgartirmaydi.
- **ffmpeg `afftdn`:** 25 ms kechikish qo'shadi ([[video-optimize]]).
- **`requirements.txt` to'liq emas (review'da tasdiqlangan):**
  - `pillow` yo'q (`clip_cover` uni import qiladi, `selftest` ham), shuning uchun yangi o'rnatishda `--quick` ham yiqiladi.
  - `demucs`, `torch` va `matplotlib` ham ro'yxatda yo'q.
  - `faster-whisper` pin qilingan, lekin hech bir skript uni ishlatmaydi.
- **SoundFont:** FluidR3_GM (142 MB) Debian paketidan olinadi, git'ga kirmaydi. Olish uchun: `sh scripts/get_soundfont.sh` ([[git-repo]]).
  - Review'da topildi: uzilgan yuklash davom ettirilmaydi (temp papka har safar o'chiriladi). Linux'da tar xatosi yashiriladi.
- **Internet:** iPhone hotspot orqali sekin. Katta yuklashdan oldin foydalanuvchiga ayt.
- **Regressiya:** `scripts/selftest.py` (`--quick` ≈7 s, to'liq ≈50 s, `--demucs`).
  - Review'da topildi: ba'zi tekshiruvlar zaif. Burun testi faqat 1.4 kHz tufayli o'tadi, limiter shipi umuman sinalmaydi, "tonikada tugaydi" doim to'g'ri chiqadi.
- Obsidian vault = `~/my_projects`, ya'ni `music_lab/` papkasining o'zi.

Bog'liq: [[voice-polish-chain]], [[vocal-on-minus]], [[minus-ajratish]], [[refaktoring-review]]
