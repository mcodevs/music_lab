---
name: refaktoring-review
description: Antigravity refaktoringi ko'rib chiqildi (7/10) va tuzatildi; uning keyingi 6 bandli rejasi Claude tomonidan bajarildi (2b atrim — QILINMADI), melody_to_song + selftest e2e qo'shildi, video sinxron xatolari topildi (2026-11-14)
metadata:
  type: project
---

# Skriptlar refaktoringi: review va tuzatishlar (2026-11-14)

Antigravity `scripts/` ni qayta yozdi: umumiy `dsp.py`, universal CLI'lar, yangi `separate_minus.py` va `video_optimize.py`. Claude ko'rib chiqdi (7/10), foydalanuvchi "Ha, tuzat" dedi va xatolar shu kuni tuzatildi. Hammasi sintetik audio va videoda qayta sinab ko'rildi.

## Nimalar o'zgardi (1-bosqich)
- **Diagnostika qayta kalibrlandi** (`dsp.diagnose_voice`):
  - HNR endi Praat uslubidagi autokorrelyatsiya bilan o'lchanadi. Natijalar: toza ≈26–28 dB, nafasli ≈16–17, xirillagan ≈6–11. Eski harmonik-taroq usuli hammasiga ≈12–14 dB berardi.
  - Burun rezonansi endi LTAS orqali o'lchanadi (1/3 oktava minus 1.5 oktava trend).
  - Chegaralar: HNR < 15 dB yoki 500 Hz > 2.5 dB / 1.4 kHz > 3.5 dB bo'lsa, `--fix-cold suggested` chiqadi. «Белтепа» shamollagan yozuvi bu shkalada ≈14 dB ([[shamollash-tuzatish]]).
- **Hech bir skript shamollash tuzatishini o'zi yoqmaydi.** `fix_cold` faqat `--fix-cold` bilan.
- **f0 keshi** `tmp/<nom>_f0_<kontent-hash>.npy` — eski kesh boshqa take'ga ishlatilmaydi.
- `vocal_on_minus.py --config`: `work_dir` config papkasidan; nisbiy yo'llar ishga tushirilgan papkaga nisbatan.
- Delay `--reverb-db` ga ergashadi (reverb − 8 dB, standart −26).
- `clip_cover.py`: intro avtomatik, uzun minus kirishida birinchi kadr ushlanadi, portret iPhone .mov → 720×1280.
- `align_analysis.py`: jimlikdagi NaN DTW tuzatildi. Loyiha git'ga olindi ([[git-repo]]).

## 2-bosqich: Antigravity'ning 6 bandli rejasi — Claude bajardi ("Ha, bajar")
| # | Band | Holat |
|---|---|---|
| 1 | `clip_cover --init`: `voice_minus_video` xcorr bilan avtomatik (r + peak ratio, WEAK ogohlantirish) | ✅ xato ~2 ms |
| 2a | `video_optimize` portret o'lchami | ✅ |
| 2b | manfiy offset uchun `atrim` | ❌ **qilinmadi** (sinxronni buzadi) |
| 2c | `--delay-db` | ✅ |
| 3 | `separate_minus`: `--work-dir` abspath, `--four-stems` qayta yig'ish, src wav o'chirish, `--project`, `--voice` (Demucs bilan take tozalash) | ✅ Demucs yo'li sinaldi |
| 4 | `vocal_on_minus` balansi: auto `min(ratio+0.5, +3.0)`, `--vocal-db` | ✅ |
| 5 | `melody_to_song.py` (hum → basic-pitch → kalit/Viterbi akkordlar → fluidsynth → mix −14) | ✅ sintetik hum'da: 22/22 nota, Am, 95.7 bpm (asli 96) |
| 6 | `selftest.py` | ✅ (pastga qarang) |

**Selftest:** Antigravity ham parallel ravishda (16:51, Claude ishlayotgan paytda) `selftest.py` ni yozdi — xuddi shu repo'da, bir vaqtda. Claude uni o'chirmadi, ustiga e2e testlar qo'shdi: melody render, vocal_on_minus (+3 cap, `--vocal-db`), clip_cover init+portret render, `--demucs`. `--quick` ≈7 s, to'liq ≈50 s, `--demucs` +13 s. `output/`/`work/` toza qoladi, `work/vocal_on_minus.json` pointer tiklanadi.

**Selftest topgan haqiqiy xatolar** ([[video-optimize]] 5-bo'lim): sinxron o'lchovi pitch-davrga sakrardi; `fps=30` snap (16.7 ms); `afftdn` 25 ms kechikish (`_optimized.mp4` doim kech edi); ffmpeg normallashtirishi. Hammasi `mux_av` bilan tuzatildi.

## Hali qolgan
- Haqiqiy shamollagan/burunli yozuvda diagnostika chegaralari tekshirilmagan (workspace tozalangan).
- `melody_to_song` faqat sintetik hum'da sinalgan; haqiqiy hum (nafas, noaniq pitch) bilan quloq bilan tekshirish kerak.
- `get_soundfont.sh` ning yuklash qismi sinalmagan.
- Ikki agent (Claude + Antigravity) bir papkada bir vaqtda yozmasin: alohida branch/worktree, keyin `git diff` bilan review.

Bog'liq: [[vocal-on-minus]], [[qiz-toping-klip]], [[video-optimize]], [[voice-polish-chain]], [[vokal-reverb-didi]], [[shamollash-tuzatish]], [[git-repo]], [[music-toolkit]]
