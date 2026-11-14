---
name: video-plugins
description: Video uchun o'rnatilgan 4 ta Claude plagini (ffmpeg-llm, watch-video, Video Cleanup, video-shotcraft), bog'liqliklar va yuklab olish tartibi
metadata:
  type: reference
---

# Video plaginlar (2026-11-13 o'rnatilgan)

claude.ai akkauntida yoqilgan (Anthropic Directory, community):

| Plagin | Vazifa | Kerak |
|---|---|---|
| **ffmpeg-llm** | so'z bilan aytilgan vazifadan ffmpeg buyrug'i (`/ffmpeg`, ffmpeg-expert agent) | ffmpeg ✅ |
| **watch-video** | videodan keyframe + transkript → Markdown hisobot | ffmpeg ✅, yt-dlp ✅, faster-whisper ✅ |
| **Video Cleanup** | nutq audiosini tozalash, LUFS, rasm sifati, logo/lower third/end card | Python + ffmpeg ✅ |
| **video-shotcraft** | Remotion bilan kinematik videolar (qo'shiq klip/vizualizatsiya) | Node 24 / npx ✅ |

Rad etilgan: ManyMotions AI Video Editor (tashqi akkaunt kerak).

## Bog'liqliklar
- **yt-dlp 2026.10.26** — brew orqali (`/opt/homebrew/bin/yt-dlp`).
- **faster-whisper 1.2.1** (ctranslate2 4.9.0) — faqat **`.venv` (Python 3.11)** da, tizim
  Python 3.14 da yo'q. `requirements.txt` ga qo'shilgan. Agar watch-video tizim `python3`
  ni chaqirsa, `.venv/bin/python` ni ko'rsatish kerak.
- Whisper modeli birinchi ishlatilganda yuklanadi (small ~0.5 GB, large ~3 GB) — hotspot
  sekin, oldindan ayt ([[music-toolkit]]).
- Plagin skill'lari faqat **yangi sessiyada** paydo bo'ladi.

## YouTube'dan yuklash tartibi
- Videolar `videos/<id>.mp4` ga saqlanadi; URL'dagi `?si=` kuzatuv parametri olib tashlanadi.
- Buyruq: `yt-dlp --no-playlist -f "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b" --merge-output-format mp4 -o "videos/%(id)s.%(ext)s" URL`
- **Tuzoq:** `ext=mp4` bo'lsa ham YouTube **AV1** video beradi (Shorts'da ham). Eski
  QuickTime/iMovie ochmasligi mumkin — kerak bo'lsa H.264 ga o'tkaz yoki `vcodec^=avc1` filtr qo'y.
- Birinchi yuklangan: `videos/i45x-iaggZk.mp4` — «Oddiygina qiz toping ona!» (MENING DUNYOYIM),
  1:30, 1080×1920 vertikal, AV1 + AAC 44.1k (2026-11-13).

Bog'liq: [[music-toolkit]], [[home-studio-gear]]
