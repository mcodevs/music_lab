---
name: refaktoring-review
description: Antigravity skriptlar refaktoringi (dsp.py + CLI) ko'rib chiqildi (7/10) va topilgan xatolar Claude tomonidan tuzatildi; diagnostika endi faqat maslahat beradi (2026-11-14)
metadata:
  type: project
---

# Skriptlar refaktoringi: review va tuzatishlar (2026-11-14)

Antigravity `scripts/` ni qayta yozdi: umumiy `dsp.py`, universal CLI'lar, yangi `separate_minus.py` va `video_optimize.py`. Claude ko'rib chiqdi (7/10), foydalanuvchi "Ha, tuzat" dedi va xatolar shu kuni tuzatildi. Hammasi sintetik audio va videoda qayta sinab ko'rildi.

## Nimalar o'zgardi
- **Diagnostika qayta kalibrlandi** (`dsp.diagnose_voice`):
  - HNR endi Praat uslubidagi autokorrelyatsiya bilan o'lchanadi. Natijalar: toza ≈28 dB, nafasli ≈17, xirillagan ≈11. Eski harmonik-taroq usuli hammasiga ≈12–14 dB berardi.
  - Burun rezonansi endi LTAS orqali o'lchanadi (1/3 oktava minus 1.5 oktava trend). Eski usul +14 dB rezonansni ham sezmasdi.
  - Chegaralar: HNR < 15 dB yoki 500 Hz > 2.5 dB / 1.4 kHz > 3.5 dB bo'lsa, `--fix-cold suggested` chiqadi. «Белтепа» shamollagan yozuvi bu shkalada ≈14 dB ga to'g'ri keladi ([[shamollash-tuzatish]]).
  - 2–3.5 kHz "ring" endi trigger emas: oddiy ovozda ham −8…−16 dB bo'ladi.
- **Hech bir skript shamollash tuzatishini o'zi yoqmaydi.** `clip_cover.py --init` endi faqat maslahat yozadi, `fix_cold` faqat `--fix-cold` bilan yoqiladi.
- **f0 keshi** endi `tmp/<nom>_f0_<kontent-hash>.npy` ko'rinishida saqlanadi: boshqa qo'shiq, boshqa take yoki `--fix-cold` bo'lsa, eski kesh ishlatilmaydi. `tmp/` ni istalgan payt o'chirish mumkin.
- `vocal_on_minus.py --config`: `work_dir` endi config papkasidan olinadi. Nisbiy yo'llar ishga tushirilgan papkaga nisbatan hisoblanadi.
- Eski yo'llar standart qiymatlardan olib tashlandi (`~/Desktop/vd.mov`, `sveta_song`, `qiz_toping`).
- Delay endi `--reverb-db` ga ergashadi (reverb − 8 dB, standart −26).
- `clip_cover.py`:
  - `--init` intro'ni o'zi hisoblaydi.
  - Minus kirishi uzun bo'lsa, birinchi kadr ushlab turiladi (oldin `AssertionError` berardi).
  - ffmpeg xatosi tekshiriladi.
  - Portret (burilgan) iPhone .mov endi 720×1280 klipga aylanadi, cho'zilmaydi.
- `align_analysis.py`: raqamli jimlikda chiqadigan NaN DTW xatosi tuzatildi.
- `.claude/skills/voice-to-music/SKILL.md` `.agents/` dagi nusxa bilan sinxronlandi.

## Hali qolgan
- Haqiqiy shamollagan/burunli yozuvda chegaralar tekshirilmagan (workspace tozalangan). Birinchi haqiqiy ovozda `--diagnose` natijasini quloq bilan solishtirish kerak.
- `separate_minus.py` (Demucs) qayta ishga tushirilmadi, uning kodi o'zgartirilmagan.
- Loyiha git'da emas. `git init` qilinsa, agentlar o'zgarishini diff bilan ko'rish mumkin bo'ladi.

Bog'liq: [[vocal-on-minus]], [[qiz-toping-klip]], [[video-optimize]], [[voice-polish-chain]], [[vokal-reverb-didi]], [[shamollash-tuzatish]]
