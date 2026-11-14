---
name: git-repo
description: music_lab git repo + PUBLIC GitHub (mcodevs/music_lab); .venv/output/work/videos va soundfont ignore qilingan, soundfont scripts/get_soundfont.sh bilan qayta olinadi; references/ hammaga ochiq (2026-11-14)
metadata:
  type: project
---

# Git repo va GitHub (2026-11-14)

Loyiha endi git'da: `main` branch, birinchi commit `72755d7`. Remote: `git@github.com:mcodevs/music_lab.git`.
Repo **public**: buni foydalanuvchi o'zi tanladi (private tavsiya qilingan edi).

## .gitignore
- Repoga kirmaydi: `.venv/`, `__pycache__/`, `.DS_Store`, `output/`, `work/`, `videos/`.
- `soundfonts/*` va `*.sf2` ham kirmaydi, chunki `FluidR3_GM.sf2` 148 MB va GitHub'ning 100 MB chegarasidan katta. Faqat `soundfonts/README.md` repoda turadi.
- Yangi kompyuterda: `sh scripts/get_soundfont.sh`. Skript Debian'dan ~120 MB yuklab, SHA-256 ni tekshiradi. Qo'lda qilish yo'li `soundfonts/README.md` da yozilgan. Yuklash qismi hali sinalmagan: foydalanuvchi 120 MB test yuklashni rad etdi. Mavjud fayl uchun "o'tkazib yuborish" holati ishladi.

**Why:** Antigravity va Claude ikkalasi ham shu papkada ishlaydi. Git bo'lmagani uchun [[refaktoring-review]] da agent o'zgarishlarini diff bilan ko'rib bo'lmagandi.
**How to apply:**
- Har bir agent ishidan keyin `git diff` / `git log` bilan tekshirish kerak.
- Commit va push faqat foydalanuvchi so'raganda qilinadi.
- Repo public, shuning uchun bu vault notalari (`references/`, `MEMORY.md`) ham push qilinsa hammaga ko'rinadi. Shaxsiy ma'lumot yozishdan oldin buni hisobga olish kerak.
- Private qilish buyrug'i: `gh repo edit mcodevs/music_lab --visibility private --accept-visibility-change-consequences`.
- sf2 yo'q bo'lsa, katta yuklash haqida avval foydalanuvchiga aytish kerak ([[music-toolkit]]: internet hotspot orqali sekin).

Bog'liq: [[refaktoring-review]], [[workspace-tozalandi]], [[music-toolkit]]
