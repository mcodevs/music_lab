---
name: qiz-toping-klip
description: scripts/clip_cover.py — a cappella video + lav-mic vokal → minus ustida klip-cover (lab-sinxron saqlanadi); «Oddiygina qiz toping ona» birinchi natija, 2026-11-14
metadata:
  type: project
---

# Klip-cover: `scripts/clip_cover.py`

**2026-11-14:** «Oddiygina qiz toping ona» klipi yig'ildi. Reverb kamaytirildi, shamollash tuzatildi ([[shamollash-tuzatish]], tasdiqlangan). 3-band (17–19 qator, +5 st) haqida alohida fikr hali yo'q.
Natija: `output/Oddiygina qiz toping ona (klip).mp4` (1280×720, 95 s, 49 MB) + `.wav/.mp3`.

Ishlatish: `.venv/bin/python -I scripts/clip_cover.py [config.json]` (~80 s). Sozlamalar skript boshidagi `CFG`
(yoki JSON bilan ustiga yoziladi): `voice`, `video`, `voice_minus_video`, `origv`, `minus`,
`orig_onsets` (24 qator), `minus_shift`, `title`, `intro`, `outro`, `target_lufs`.

## Kirishlar va o'lchovlar
- `~/Desktop/vd.mov` (Mac kamera 720p, audio 16 kHz — yaroqsiz) + `~/Downloads/Белтепа улица 9.m4a`
  (o'sha ijro, iPhone + J6 lav, [[home-studio-gear]]). Memo videodan **3.36 s** oldin boshlanadi.
- Vokal Demucs bilan tozalandi (xona shovqini −43 LUFS edi).
- Minus [[minus-ajratish]] dan: G minor, 86 BPM. Foydalanuvchi minussiz kuylagan; tempi originalga
  deyarli teng (x0.9997), qatorlar ±68 ms.

## Zanjir (vocal-on-minus'dan farqi)
- **Qator darajasida moslash:** 24 qator boshlanishi minus to'riga tortiladi, qator ichidagi frazirovka
  saqlanadi. Ovoz VA video bitta vaqt xaritasi bilan cho'ziladi (0.93–1.08) → lab-sinxron buzilmaydi.
  Natija: qator boshlanishi xatosi median 4 ms, max 17 ms.
- **Minus** foydalanuvchi toniga: **+5 st** (G min → C min; −7 o'rniga, kichikroq siljish).
- **Ton driftini tuzatish:** har qatorda melodiya konturini originalga DTW bilan solishtirib,
  interval o'lchanadi. Natija: 1–12 qatorlar ≈0, 13–16 +1.5…2, **17–19 (3-band) +4.4…5.4** —
  foydalanuvchi u bandni ~kvarta past kuylagan (kontur bir xil, IQR 0.6–1.1), 20–24 +1…2.3.
  Nota darajasida yumshoq korreksiya (kuch 0.6): 29 → 12 sent xato.
- **Reverb:** birinchi versiya (−12 dB, room 0.66, delay −20) foydalanuvchiga **juda ho'l** tuyuldi →
  standart endi `reverb_db=-18, room=0.5, delay_db=-26` (CFG). Bu foydalanuvchi quruqroq vokalni yoqtiradi.
- Match-EQ YO'Q (original ayol ovozi). Vokal minusdan +3 dB (original +4.6 — juda vokal-oldinda).
- Video: iliq grade, vinyetka, sekin push-in (7%), engil grain, Didot sarlavha (Pillow PNG overlay —
  ffmpeg'da **drawtext yo'q**, freetype'siz yig'ilgan), qora fonga yakuniy kadr.

## Tuzoqlar
- Whisper auto-til o'zbekni `fa` deb taniydi → `language="uz"`; baribir matn sifatsiz,
  shuning uchun subtitr qo'yilmadi (to'g'ri matn foydalanuvchidan kerak).
- Xromaga asoslangan akkord-moslik testi ton siljishini aniqlashda ishonchsiz chiqdi; kontur-DTW ishonchli.
- `noise=alls=5` grain + CRF17 → 257 MB; `alls=2`, CRF19, `-tune grain`, maxrate 12M → 49 MB.
- ffmpeg 9: `-vsync` yo'q → `-fps_mode`; `crop` w/h da `t` ishlamaydi (zoom Python'da qilinadi).

Bog'liq: [[vocal-on-minus]], [[minus-ajratish]], [[video-plugins]], [[voice-polish-chain]]
