---
name: refaktoring-review
description: Antigravity refaktoringi (7/10) tuzatildi; uning 6 bandli rejasi Claude tomonidan bajarildi (2b atrim — yo'q); 2026-11-14 to'liq loyiha review'i (3 agent) — ~45 kamchilik, eng og'irlari clip_cover VFR drift va kirill sarlavha, tuzatilmagan
metadata:
  type: project
---

# Skriptlar refaktoringi: review va tuzatishlar (2026-11-14)

## 1-bosqich: Antigravity refaktoringi (7/10) → tuzatildi
- Diagnostika qayta kalibrlandi:
  - HNR — Praat uslubidagi autokorrelyatsiya;
  - burun rezonansi — LTAS.
- Diagnostika faqat maslahat beradi, `fix_cold` faqat `--fix-cold` bilan yoqiladi ([[shamollash-tuzatish]]).
- f0 keshi kontent-hash bilan saqlanadi.
- `clip_cover`: intro avtomatik, uzun minus kirishida kadr ushlanadi, portret 720×1280.
- Delay = reverb − 8 dB. Loyiha git'ga olindi ([[git-repo]]).

## 2-bosqich: Antigravity'ning 6 bandli rejasi — Claude bajardi
Bajarilganlar:
- offset avto-topish;
- `video_optimize` portret, `--delay-db`;
- `separate_minus` uchun `--project` va `--voice`;
- vokal balansi cheklovi (+3 dB) va `--vocal-db`;
- `melody_to_song.py`;
- `selftest.py` (Antigravity parallel yozdi, Claude e2e testlar qo'shdi).

2b (atrim) **qilinmadi**.

Selftest topgan va tuzatilgan video sinxron xatolari: [[video-optimize]] 5-bo'lim. Commit `aedd928`, keyin `main` ga push qilindi.

## 3-bosqich: to'liq loyiha review'i (2026-11-14, Antigravity to'xtagan)
Kod 3 qismga bo'linib, 3 ta agentga berildi. Ular sintetik media bilan amalda sinashdi. Eng og'ir topilmalarni Claude kodda qayta tasdiqladi.

Natija: **~45 kamchilik, hali hech biri tuzatilmagan.** Batafsil ro'yxat:
- `vocal_on_minus` / `phrase_timing` → [[vocal-on-minus]];
- `melody_to_song`, `requirements.txt`, `get_soundfont.sh`, selftest → [[music-toolkit]].

### Eng og'irlari (foydalanuvchi ishiga bevosita ta'sir qiladi)
- **`clip_cover` VFR lab-sinxron drifti** (tasdiqlangan, emulyatsiya):
  - kadrlar `avg_frame_rate` bo'yicha indekslanadi, lekin ffmpeg rawvideo CFR'da (`r_frame_rate`) dekod qiladi;
  - 300 kadrdan 1 tasi tushib qolgan telefon videosida 4 daqiqalik qo'shiq oxiriga kelib ~0.7 s siljiydi;
  - yechim: `-vf fps=30` bilan dekod qilish va 30 bo'yicha indekslash.
- **Kirill sarlavha to'rtburchak bo'lib chiqadi:** `clip_cover` sarlavhasi Didot shriftida, unda kirill glyph'lari yo'q (fontTools bilan tasdiqlandi). Avenir Next'da kirill bor.
- **Avto-offset noto'g'ri** (`clip_cover`), ikki holatda:
  - video audiodan >1 kadr keyin boshlansa;
  - .ts/.MTS fayllarda (format `start_time` ayrilmaydi).
- **`vocal_on_minus` umumiy papka:** `--project` siz ishlatilsa, `work/phrase_shifts.json` qo'shiqlar orasida umumiy bo'ladi. `--suggest` qayta ishga tushirilsa, eski tuzatishni bekor qiladi.
- **`vocal_on_minus` yiqiladi**, agar ovoz originalning yarmidan qisqa bo'lsa.
- **`melody_to_song` minor tonallik:** V akkord hech qachon tanlanmaydi va kuylangan G# bilan to'qnashadi.
- **`requirements.txt` to'liq emas:** pillow, demucs, torch va matplotlib yo'q, shuning uchun yangi o'rnatish buziladi.
- **Maxfiylik:** public repoda shaxsiy notalar bor ([[git-repo]]).

### clip_cover / separate_minus / video_optimize: qolganlari
- `clip_cover`:
  - 48 kHz minus berilsa, `assert` bilan yiqiladi;
  - video oxirgi qatordan oldin tugasa, qator jimgina kesiladi (rubberband stderr yutiladi);
  - reverb dumi minusning o'zining oxiridan olinadi, kesilgan joydan emas;
  - rang BT.601 bilan kodlanadi va teglanmaydi (rang siljiydi);
  - tmp papka (qo'shiq boshiga ~170 MB) tozalanmaydi.
- `separate_minus`:
  - Demucs `--clip-mode rescale` stem gain'larini buzishi mumkin (taxminiy);
  - Demucs xato bersa, temp wav qoladi;
  - `--device` uchun cpu fallback yo'q, help esa bor deb aytadi.
- `video_optimize`:
  - 0.4 s dan qisqa klip NaN bilan yiqiladi;
  - jim audioda soxta "−500 ms WARNING" chiqadi.

### Mustahkam chiqqanlar
- `video_optimize` sinxroni: barcha holatlarda haqiqiy xato 0.0 ms — VFR, 25/60 fps, ±offset, .ts, burilgan video, 44.1/48k, kirill va qo'shtirnoqli fayl nomlari.
- Rotation ±90/180/270.
- Demucs nomlash va slug.
- Diagnostika guard'lari, `master_limiter`, Match-EQ, Rubber Band pitchmap birliklari.
- Akkord jadvali, Viterbi, bas oktavasi.
- `get_soundfont.sh` macOS'da: sintetik .deb bilan to'liq oqim ishladi; real URL 200 qaytaradi, SHA mos keladi.

## Hali qolgan
- Yuqoridagi kamchiliklarni tuzatish: foydalanuvchi ustuvorlikni tanlaydi.
- Haqiqiy shamollagan ovozda diagnostika chegaralarini tekshirish.
- Haqiqiy xirgoyida `melody_to_song` ni quloq bilan tekshirish.
- Agentlar alohida branch'da ishlasin.

Bog'liq: [[vocal-on-minus]], [[qiz-toping-klip]], [[video-optimize]], [[music-toolkit]], [[voice-polish-chain]], [[shamollash-tuzatish]], [[git-repo]]
