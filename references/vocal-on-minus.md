---
name: vocal-on-minus
description: scripts/vocal_on_minus.py — a cappella vokalni minusga moslab (vaqt + pitch) aralashtirish; CLI --project, quruq standartlar; 2026-11-14 to'liq review'da topilgan ma'lum kamchiliklar ro'yxati
metadata:
  type: project
---

**2026-11-13:** «Мои слезы» (Света) cover'i shu skript bilan qilindi va foydalanuvchi tasdiqladi. Natija: `output/Мои слезы (мой вокал).mp3/.wav` + `... - vokal stem.wav`.

**Ishlatish (2026-11-14 dan):**
```
separate_minus.py song.m4a --name "Song" --project work/<nom> --voice take.m4a
vocal_on_minus.py --project work/<nom> --out "Nom"
```
Qo'shimcha flaglar: `--vocal-db`, `--fix-cold`, `--align global|local|shift`. Natija −12 LUFS.

Zanjir:
1. Frazalarni aniqlash (librosa split).
2. Original vokalga DTW bilan moslash (chroma + RMS + onset). Qo'shiqchi 10 s dan uzun cholg'u tanaffusini tashlab ketgan bo'lsa, skript buni o'zi aniqlaydi.
3. Har bir fraza uchun Rubber Band: `--pitchmap` (75 %, vibrato saqlanadi) va `-M` timemap stretch.
4. Vokal zanjiri: original tembrga match-EQ, de-esser, kompressor/EQ, quruq reverb −18 dB / room 0.5, delay −26 dB ([[vokal-reverb-didi]]).
5. Vokal balansi `min(original + 0.5, +3 dB)`; sidechain duck; limiter.

**Qo'lda to'g'rilash:** `<project>/phrase_shifts.json` faylida `[{"from": "1:26.0", "to": "1:27.9", "shift_ms": 150}]` (+ kechroq degani). `phrase_timing.py --suggest` ham taklif beradi.

## Ma'lum kamchiliklar (2026-11-14 to'liq review; hali tuzatilmagan)
Kodda tasdiqlangan:
- Ovoz originalning yarmidan kam yoki raqamli jim bo'lsa, `np.concatenate(vt_all)` bo'sh ro'yxatda yiqiladi.
- Tanaffus tashlab o'tilganda, undan keyingi birinchi fraza tanaffus ichiga erta tushishi mumkin. Sabab: segmentlar o'rtachalanadi va 0.6 s silliqlash qo'llanadi.
- `--suggest` qayta ishga tushirilsa, avvalgi tuzatishni bekor qiladi. U lag'ni qo'shmaydi, almashtiradi.
- `--project` siz ishlatilganda `work/phrase_shifts.json` hamma qo'shiqlar uchun umumiy, ya'ni bir qo'shiqning tuzatishlari boshqasiga o'tadi.
- Project ichidagi `config.json` da berilgan yo'llarni avto-topilgan `voice.wav` va boshqalar bosib ketadi.
- `shift_ms` kasr son bo'lsa (masalan `120.0`), `:+d` formati ValueError beradi.
- Mono minus berilsa, vokal 3 dB past chiqadi (mono kabi o'lchanadi, lekin stereoga ko'chiriladi).
- Vaqtinchalik `ph*_in.wav` fayllari 16-bit yoziladi, shuning uchun 0 dBFS dan oshgan qism kesiladi.
- Timemap "0 0" bilan boshlanadi; fraza 0-sample'dan boshlansa, kalit kadr takrorlanadi (25–64 ms xato).
- 0.3 s dan qisqa frazalar umuman render qilinmaydi.

Taxminiy (tasdiqlanmagan):
- Pitch maqsadi global joylashuvdan olinadi. ±1 semiton oyna to'g'ri kuylangan notani qo'shnisiga tortib ketishi mumkin.

Yechim rejasi review natijasida: [[refaktoring-review]].

**Why:** foydalanuvchi telefonda yozgan vokaldan studiyaviy cover xohlaydi va vaqtni quloq bilan baholaydi.
**How to apply:** noto'g'ri joylarni foydalanuvchidan quloq bilan so'rab, `phrase_shifts.json` ga yoz; bitta metrikaga ishonma. Faqat ovozni chiroyli qilish kerak bo'lsa — [[voice-polish-chain]].

Bog'liq: [[home-studio-gear]], [[music-lab-voice-cover-done]], [[minus-ajratish]], [[refaktoring-review]]
