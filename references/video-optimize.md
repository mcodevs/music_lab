---
name: video-optimize
description: Videoni optimallashtirish + ovozga effekt retsepti — H.264 CRF 20, 2-pass loudnorm, voice_polish.py bilan qayta mux, audio offset tuzog'i; Untitled2/3.mov (2026-11-14)
metadata:
  type: reference
---

# Video + audio optimallashtirish retsepti (2026-11-14)

Foydalanuvchi "optimize this video and audio" desa — shu zanjir ishlatildi, natija yaxshi chiqdi
(eshitib tasdiqlanmagan hali).

**Kirish:** `~/Desktop/Untitled3.mov` — 720p, H.264 Main 10.6 Mbps, VFR, mono AAC, −21.4 LUFS.
Kontent: J6 lav mic'ga a cappella kuylash (AirPods quloqda).
**Chiqish:** `~/Desktop/Untitled3_optimized.mp4` — 25 MB (−59%), SSIM 0.988, −14.1 LUFS, peak −4.4 dBFS.
Original o'zgartirilmaydi, yoniga `_optimized.mp4` yoziladi.

## 1. Optimallashtirish zanjiri
1. Probe: `ffprobe` + `ebur128` / `volumedetect` bilan boshlang'ich LUFS.
2. Loudnorm 1-pass o'lchov (`print_format=json`), so'ng 2-pass `measured_*` + `linear=true`.
3. Encode:
   - Video: `fps=30` (VFR → CFR), `libx264 -preset slow -crf 20 -profile:v high -g 60`, bt709 teglar.
   - Audio: `highpass=f=70, afftdn=nf=-30:tn=1, loudnorm I=-14 TP=-1.5 LRA=11` → AAC 160k stereo.
   - `-movflags +faststart` (ijtimoiy tarmoq/web uchun).
4. Tekshiruv: ebur128 (I, peak) + SSIM originalga nisbatan (≥0.98 maqsad).

## 2. Ovozga effekt qo'shish (keyingi so'rov)
- Originaldan audio ajratildi (48k mono wav) → `scripts/voice_polish.py <wav> untitled3_polished -18 0.5`
  (quruq did: [[vokal-reverb-didi]]) → `output/untitled3_polished.{wav,mp3}`, −15 LUFS, peak −2.3.
- Optimized videoga `-c:v copy` bilan qayta mux → `~/Desktop/Untitled3_effects.mp4` (AAC 192k).
- **Tuzoq — lab-sinxron:** .mov da audio `start_time` 0 emas (Untitled3: 0.1668). librosa wav'ni 0 dan
  boshlaydi, shuning uchun mux'da `-itsoffset <start_time>` qo'yish shart; `-shortest` ishlatma (videoni kesadi).
  Har doim `ffprobe -show_entries stream=start_time` bilan tekshir.
- Holat: eshitib tasdiqlanmagan; reverb ko'p desa −22 dB ga tushir.

## 3. Untitled2.mov ("buni ham")
- 64 MB, 49.8 s, −24.4 LUFS, audio offset **0.217 s** → `Untitled2_optimized.mp4` (23 MB, −13.9 LUFS, SSIM 0.989)
  va `Untitled2_effects.mp4` (voice_polish −18/0.5, −15 LUFS). Default endi: ikkala versiyani birga chiqar.
- Tuzoq: zsh'da `g` alias bor — shell funksiyani `g(){}` deb nomlama (parse error).

## 4. umar_onam.mov — bola "Onam" kuylaydi (2026-11-14)
- "Studiyadagidek tiniq qil" → `voice_polish.py work/umar_onam/voice.wav "Umar - Onam (studio)" -18 0.5`
  → `output/Umar - Onam (studio).{wav,mp3}` (−15 LUFS, peak −3) → `~/Desktop/umar_onam_studio.mp4`.
- Shovqin fon −72 dB (iPhone o'zi tozalagan) — denoise kerak bo'lmadi.
- **Mux usuli (afzal):** `-itsoffset` o'rniga `-af "adelay=<start_ms>|<start_ms>"` (start_time=0.1467 → 147).
- **Sinxron tekshiruvi tuzog'i:** `ffmpeg -vn` decode `start_time` ni tashlab yuboradi → noto'g'ri "lag".
  To'g'ri: `-af aresample=async=1:first_pts=0` bilan ikkala faylni decode qilib xcorr (natija 0.25 ms).
- Holat: foydalanuvchi eshitib tasdiqlamagan.

Bog'liq: [[video-plugins]], [[voice-polish-chain]], [[home-studio-gear]].
