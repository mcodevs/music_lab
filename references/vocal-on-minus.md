---
name: vocal-on-minus
description: scripts/vocal_on_minus.py — a cappella vokalni qo'shiq minusiga moslab (vaqt + pitch), studiya effektlari bilan aralashtirish; yangi cover so'rovlarida qayta ishlat
metadata:
  type: project
---

**2026-11-13:** «Мои слезы» (Света) cover'i shu skript bilan qilindi va foydalanuvchi tasdiqladi. Natija: `output/Мои слезы (мой вокал).mp3/.wav` + `... - vokal stem.wav`.

Ishlatish: `.venv/bin/python -I scripts/vocal_on_minus.py`
Kirishlar skript boshida qattiq yozilgan (yangi qo'shiq uchun o'zgartir):
- `VOICE` — foydalanuvchi vokali, Demucs bilan tozalangan (`work/separated/htdemucs_ft/voice/vocals.wav`)
- `ORIGV` / `MINUS` — original qo'shiqning Demucs vokal va minus stem'lari (`htdemucs_ft/<qo'shiq>/vocals.wav`, `no_vocals.wav`)
- `OUTNAME`, `TARGET_LUFS = -12`, `PITCH_STRENGTH = 0.75`

Zanjir:
1. Fraza aniqlash (librosa split, top_db 35)
2. DTW (chroma + RMS + onset) bilan original vokalga moslash; 10 s+ cholg'u tanaffusini qo'shiqchi tashlab o'tganmi — avtomatik tekshiradi va bo'lib moslaydi
3. Har fraza: yengil pitch correction (original melodiyaga, vibrato saqlanadi, ±1 semiton) + Rubber Band R3 bilan time-stretch (formant saqlanadi, nisbat 0.6–1.6)
4. Original vokal tembriga match-EQ (±6 dB), de-esser 5–11 kHz, EQ/kompressor, plate reverb (−13 dB) + 3/8 beat delay (−21 dB)
5. Minus ustiga original vokal/minus balansida (+0.5 dB), yengil sidechain ducking, limiter → −12 LUFS, WAV 24-bit + MP3 320k

Qo'lda to'g'rilash: `work/phrase_shifts.json` — `[{"from": "1:26.0", "to": "1:27.9", "shift_ms": 150}]` (+ = kechroq). `scripts/phrase_timing.py --suggest` ham taklif beradi. `ALIGN` env: `global` (eng yaxshi natija), `local`, `shift` (eksperimental).

**Why:** foydalanuvchi telefonda yozgan vokaldan studiyaviy cover xohlaydi; vaqtni quloq bilan baholaydi.
**How to apply:** yangi cover uchun avval Demucs bilan stem'larni ajrat, yo'llarni almashtir, ishga tushir; noto'g'ri joylarni foydalanuvchidan quloq bilan so'rab `phrase_shifts.json` ga yoz — bitta metrikaga ishonma. Faqat ovozni chiroyli qilish kerak bo'lsa — [[voice-polish-chain]].

Bog'liq: [[home-studio-gear]], [[music-lab-voice-cover-done]]
