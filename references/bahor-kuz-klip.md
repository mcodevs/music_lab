---
name: bahor-kuz-klip
description: «Bahor-Kuz» (Sitora Farmonova ft. Mirjamol) — qo'shiq bilan birga kuylangan iPhone video → klip-cover; clip_cover.py ga yangi --sing-along rejimi (2026-11-15)
metadata:
  type: project
---

# «Bahor-Kuz» sing-along klip (2026-11-15)

Kirish: `~/Downloads/IMG_2409.MOV` (iPhone SE, vertikal 1080×1920 HEVC, 3:33, audio 48 kHz mono) +
YouTube `S03M1P15L6c` («Karaoke | Lyrics» deb yozilgan, lekin **vokali bor to'liq qo'shiq** —
Demucs: vokal −15.2, minus −14.8 LUFS). Shuning uchun u ham minus, ham asl vokal mo'ljali bo'ldi.

## O'lchovlar
- Ijro qo'shiq bilan **birga** quloqchinda kuylangan: kamera audiosida minus yo'q (−44.8 LUFS),
  ovoz asl vokalga global **+2.212 s** (r=0.81), qator ichida ±50 ms.
- Ton bir xil: ayol qismi unison, erkak qismi (Mirjamol) **oktava yuqorida**; joylarda 30–50 sent past.
- Diagnoz `--fix-cold` taklif qildi (HNR 13.7 dB) — qo'llanmadi, faqat eshitib keyin.

## Yangi: `clip_cover.py --init ... --sing-along`
- Bitta global siljish (envelope xcorr), qatorlar cho'zilmaydi (ratios 1.000) → lab-sinxron o'lchandi **0 ms**.
- Qator bo'yicha ton "drifti" tuzatishi faqat ≤0.75 st va IQR ≤1.0 bo'lsa: duet qismida asl stemda
  ikki ovoz garmoniyada → pYIN adashib ±2–5 st yolg'on tuzatish berdi (46 dan 21 qator 0 ga).
- `minus_shift` endi oktavaga buklangan intervallar medianasi (eskisi bu yerda −2 st berardi — xato).
- Nota korreksiyasi: 24 → 10 sent. Reverb quruq ([[vokal-reverb-didi]]). Vokal balansi asldek (−0.4 dB).

## Natija
`output/Bahor-Kuz (klip).mp4` (720×1280, 247 MB), `(klip, Telegram).mp4` (CRF 23, 5M → 107 MB),
`(klip).mp3/.wav`, `(minus)`, `(vokal)`. Loyiha: `work/bahor_kuz/clip.json`.
Commit qilinmagan; foydalanuvchi bahosi hali yo'q.

## Tuzoq
- iPhone manbasi (damask gul qog'oz + grain) CRF 19 da 9.3 Mbps → 247 MB; ulashish uchun CRF 23 nusxa.

**Why:** qo'shiq bilan birga kuylangan yozuvni a cappella kabi qatorma-qator cho'zish vaqtni buzadi,
ton tuzatish esa duetda yolg'on siljish beradi.
**How to apply:** quloqchinda qo'shiq bilan kuylangan bo'lsa — `--sing-along`; noto'g'ri joylarni
foydalanuvchidan quloq bilan so'ra.

Bog'liq: [[qiz-toping-klip]], [[minus-ajratish]], [[vocal-on-minus]], [[vokal-reverb-didi]], [[home-studio-gear]]
