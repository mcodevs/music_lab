---
name: voice-polish-chain
description: scripts/voice_polish.py (+ voice_cold_fix.py) — telefon ovoz memosini tozalash va effekt bilan chiroyli qilish zanjiri; "ovozni chiroyli qil" / "shamollaganman" so'rovlarida qayta ishlat
metadata:
  type: project
---

**2026-11-13:** «Белтепа улица 11.m4a» (iPhone memo, a cappella kuylash, ~1:33, f0 ≈ 100–185 Hz) uchun `scripts/voice_polish.py` yozildi.
Natija: `output/Белтепа улица 11 (effekt).mp3/.wav`.

Ishlatish: `.venv/bin/python scripts/voice_polish.py <kirish audio> "<chiqish nomi>"`

Zanjir (pedalboard):
- EQ: HPF 85 Hz, −4 dB @190 Hz (g'o'ng'illash), −2.5 dB @380 Hz (mud), −1 dB @1.1 kHz, +3 dB @3.2 kHz (presence), +4 dB high-shelf 9 kHz (air)
- Spektral de-esser 5–11 kHz → 2 bosqichli kompressor
- Plate reverb (35 ms pre-delay, −11 dB), delay 0.375 s (−20 dB), chorus stereo dubl (−18 dB)
- −15 LUFS, limiter, peak ≈ −1…−3 dBFS

## Shamollagan / xirillagan ovoz
Foydalanuvchi shu yozuvda shamollagan edi. `scripts/voice_cold_fix.py <in.wav> <out.wav> [reduce_db=9]` polishdan OLDIN ishlatiladi:
pyin f0 → garmonik "comb" maska, garmonikalar orasidagi shovqinni 4 kHz gacha −9 dB pasaytiradi, faqat voiced kadrlarda (undoshlar/sibilyantlarga tegmaydi).
Natija: HNR 16.6 → 19.4 dB, umumiy balandlik atigi −0.5 dB. Fayl: `output/Белтепа улица 11 (effekt, tozalangan).mp3/.wav`.
- Gotcha: pyin `voiced_prob` kuylangan notalarda ko'pincha past (median 0.43) — gating uchun `voiced_flag` ishlat, aks holda effekt deyarli 0.
- Intonatsiya o'rtacha 25 cent (A440 ga nisbatan tasodifiy) — a cappella bo'lgani uchun pitch-correction qilinmadi.

**Why:** telefon memolarida 80–250 Hz ortiqcha, 4 kHz+ xira; shamollashda esa garmonikalar orasida "havo"/xirillash ko'payadi.
**How to apply:** yangi ovoz memosi kelsa, avval spektr balansi va HNR ni tekshir; xirillash bo'lsa cold_fix → polish. Reverb/delay darajasini foydalanuvchi didiga qarab sozla. Qo'shiq ustiga vokal uchun esa [[vocal-on-minus]] (`scripts/vocal_on_minus.py`).

Bog'liq: [[home-studio-gear]], [[music-lab-voice-cover-done]]

## Reverb miqdori
Foydalanuvchi standart reverb (−11 dB, room 0.72) a cappella uchun ko'p bo'lishi mumkinligini aytdi. Endi `voice_polish.py <in> <name> [reverb_db] [room]` deb chaqiriladi, delay reverbdan 9 dB past turadi.
Quruq variant: `-16 0.55`. Pauzalardagi reverb dumi kuylashga nisbatan −26 dB dan −37.5 dB gacha tushdi. Fayl: `output/Белтепа улица 11 (tozalangan, kam reverb).mp3`.
**How to apply:** musiqasiz a cappella yozuvlar uchun quruq variantdan boshla.
