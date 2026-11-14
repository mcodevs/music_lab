---
name: shamollash-tuzatish
description: Shamollagan ovoz — xirillash (voice_cold_fix.py) + dimog'li "ming'illagan" tembr (voice_denasal.py 0.7, tasdiqlangan) tuzatish zanjiri
metadata:
  type: project
---

# Shamollagan ovozni tuzatish (2026-11-14) — ✅ tasdiqlandi

Foydalanuvchi ikkinchi marta shamollab kuylagan ([[voice-polish-chain]] da birinchisi).
Bu safar shikoyat: **"ovoz biroz ming'illagan"** — burun bitgani sabab dimog'li tembr.
Natija: foydalanuvchi **"Yaxshi chiqdi"** dedi (kuch 0.7, cold_fix 7 dB).

## Zanjir (Demucs tozalashdan keyin, effektlardan oldin)
```
.venv/bin/python -I scripts/voice_cold_fix.py vocals.wav cold.wav 7     # xirillash, HNR
.venv/bin/python -I scripts/voice_denasal.py  cold.wav fixed.wav 0.7    # ming'illash
```
`voice_denasal.py`:
1. Dinamik rezonans bosish 350–1900 Hz: har kadrda 1-oktava konvertdan > 3 dB chiqqan binlar
   pasaytiriladi (max 7 dB × kuch), faqat faol kadrlarda, vaqt/chastota bo'yicha silliqlangan.
2. Statik EQ: −2 dB @ 520 Hz, −2 dB @ 1.35 kHz, +3.5 dB @ 2.8 kHz (× kuch). Balandlik saqlanadi.

## O'lchovlar («Белтепа улица 9», lav mic)
- Asl: 500 Hz rezonans +6 dB, 1.35–1.6 kHz +4.6 dB, 2–3.5 kHz 1 kHz dan **−13 dB** past (ring yo'q). HNR 12.6 dB.
- cold_fix 7 dB → HNR 14.0; denasal → 14.4.
- Kuch: 0.5 → box −3.4 / honk −2.8 / ring +2.1; **0.7 → −4.7 / −4.0 / +2.8 (tasdiqlangan)**;
  1.0 → −6.8 / −5.6 / +3.8 (ovozni yupqalashtirishi mumkin).
- Solishtirish: `output/Shamollash tuzatish (oldin - keyin).mp3`.

## Tuzoq
- [[qiz-toping-klip]] da beat_track har ishga tushishda boshqa natija berdi (86 → 89 BPM, delay ritmdan
  chiqdi) — endi tempo o'zgarmagan asl minus faylidan / slope bilan o'lchanadi (yoki `CFG['bpm']`).

**Why:** shamollash ikki xil eshitiladi: xirillash (garmonikalar orasida shovqin) va ming'illash
(burun rezonansi + 2–3 kHz yo'qolishi) — birinchisi uchun cold_fix, ikkinchisi uchun denasal.
**How to apply:** "shamollagandim" desa — spektrni o'lchab qaysi biri ekanini aniqla, darhol
cold_fix 7 + denasal 0.7 bilan boshla (tasdiqlangan), A/B fayl ber. Reverb quruq ([[vokal-reverb-didi]]).

Bog'liq: [[voice-polish-chain]], [[qiz-toping-klip]], [[home-studio-gear]]
