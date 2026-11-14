---
name: minus-ajratish
description: Original qo'shiqdan minus (instrumental) va vokalni Demucs htdemucs_ft bilan lokal ajratish retsepti va sifat tekshiruvi
metadata:
  type: project
---

# Minus ajratish (2026-11-13)

**Qaror:** minusni internetdan qidirish o'rniga **lokal AI bilan ajratamiz** (Demucs).
Qaroqchilik saytlaridan fayl yuklanmaydi; foydalanuvchining o'z fayli shaxsiy ishlatish uchun ajratiladi.

```
ffmpeg -i qo'shiq.m4a -ar 44100 work/song.wav
.venv/bin/python -I -m demucs -n htdemucs_ft --two-stems vocals -d mps --float32 -o work/separated work/song.wav
```

- `htdemucs_ft` — 4 modelli eng sifatli variant (~320 MB, `~/.cache/huggingface`, bir marta yuklanadi).
- MPS (M-chip GPU) da 3 daqiqalik qo'shiq **~30 s** da ajraladi.
- `--two-stems` olib tashlansa — 4 stem (drums/bass/other/vocals).
- Kirill nomli fayllarni avval lotin nomli wav'ga o'gir.

## Sifat tekshiruvi

Minusning o'zini yana `htdemucs` dan o'tkazib, qolgan vokal o'lchanadi.
«Света — Мои слезы» da: **−54.6 dB** (amalda eshitilmaydi). Chegara: < −40 dB yaxshi.
Minus −14.9 LUFS, asl vokal −14.0 LUFS — bu nisbat keyin miksda ishlatildi ([[vocal-on-minus]]).

Natija: `output/Света - Мои слезы (минус).mp3/.wav`, `(вокал).mp3`.

**Why:** Demucs ajratgan vokal stem keyingi ish uchun ham kerak — foydalanuvchi ovozini
asl ijrochiga moslashtirishda mo'ljal bo'ladi.
**How to apply:** yangi qo'shiq kelsa shu ikki buyruq; agar bek-vokal/xor qoldig'i sezilsa, 4 stem bilan qayta ajrat.

## Videodan ajratish (2026-11-13)

Video bo'lsa avval audio: `ffmpeg -i videos/<id>.mp4 -vn -ar 44100 -ac 2 work/<nom>/song.wav`, keyin yuqoridagi Demucs.
«Oddiygina qiz toping ona» (YouTube Shorts, [[video-plugins]]): 1:30 → ~21 s, minusda qolgan vokal
**−57.3 dB**. Asl −11.0, minus −17.4, vokal −12.8 LUFS (vokal 89/90 s davom etadi).
Natija: `output/Oddiygina qiz toping ona (minus|vokal).wav/.mp3`.

Bog'liq: [[music-toolkit]], [[music-lab-voice-cover-done]], [[video-plugins]]
