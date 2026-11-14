---
name: vokal-reverb-didi
description: Foydalanuvchi quruq vokalni yoqtiradi — reverb ikki marta "ko'p" deyildi; barcha vokal zanjirlari uchun boshlang'ich qiymatlar
metadata:
  type: feedback
---

# Vokal reverb — quruqroq boshla

Foydalanuvchi standart reverbni **ikki marta** ko'p dedi:
- 2026-11-13 — [[voice-polish-chain]] (−11 dB, room 0.72) → quruq variant `-16 0.55` ma'qul bo'ldi.
- 2026-11-14 — [[qiz-toping-klip]] (−12 dB, room 0.66, delay −20) → "Reverb ko'payib ketipti".

**Qoida:** har qanday vokal zanjirida (`voice_polish.py`, `vocal_on_minus.py`, `clip_cover.py`)
reverb ≈ **−18 dB**, room ≈ **0.5**, delay ≈ **−26 dB** dan boshla. Ko'proq kerak bo'lsa —
foydalanuvchi o'zi so'raydi; kamaytirishni kutib o'tirma.

**Why:** ikkala safar ham mening standartim (−11/−12 dB) foydalanuvchi didiga juda ho'l chiqdi.
**How to apply:** yangi cover/klip/polish so'rovida darhol quruq qiymatlar bilan render qil.
`vocal_on_minus.py` da hali −13 dB qattiq yozilgan — keyingi safar ishlatishda pasaytir.

Bog'liq: [[vocal-on-minus]], [[voice-polish-chain]], [[qiz-toping-klip]]
