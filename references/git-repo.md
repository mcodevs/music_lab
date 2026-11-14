---
name: git-repo
description: music_lab git repo + PUBLIC GitHub (mcodevs/music_lab); .gitignore va soundfont qayta olish; holat — antigravity/improvements (aedd928 + notalar) main'ga fast-forward qilinib push qilindi (2026-11-14)
metadata:
  type: project
---

# Git repo va GitHub (2026-11-14)

Loyiha git'da. Remote: `git@github.com:mcodevs/music_lab.git`.
Repo **public**: buni foydalanuvchi o'zi tanladi (private tavsiya qilingan edi).

## Holat (2026-11-14 kechqurun)
- Antigravity checkout'ni 16:45 da lokal **`antigravity/improvements`** branch'iga o'tkazgan. "Commit" so'rovi shu branch'ga **`aedd928`** ni yozdi:
  - `melody_to_song.py` va `selftest.py`;
  - video lab-sinxron tuzatishlari ([[video-optimize]]);
  - [[refaktoring-review]] rejasi.
- Commit'da Claude va Antigravity o'zgarishlari aralash.
- Foydalanuvchi "merge + push" dedi:
  - notalar commit qilindi;
  - `main` checkout'siz fast-forward qilindi (`git fetch . antigravity/improvements:main`);
  - `git push origin main` bajarildi.
- Checkout `antigravity/improvements` da qoldirildi, chunki Antigravity shu branch'da ishlayapti. Branch remote'ga push qilinmagan.

## .gitignore
- Repoga kirmaydi: `.venv/`, `__pycache__/`, `.DS_Store`, `output/`, `work/`, `videos/`.
- `soundfonts/*` va `*.sf2` ham kirmaydi, chunki `FluidR3_GM.sf2` 148 MB (GitHub chegarasi 100 MB). Faqat `soundfonts/README.md` repoda turadi.
- Yangi kompyuterda `sh scripts/get_soundfont.sh` ishlatiladi: Debian'dan ~120 MB yuklaydi va SHA-256 ni tekshiradi.
  - Yuklash qismi hali sinalmagan: foydalanuvchi test yuklashni rad etdi.

**Why:** Antigravity va Claude ikkalasi ham shu papkada, ba'zan bir vaqtda ishlaydi. Git bo'lmasa, agent o'zgarishlarini diff bilan ko'rib bo'lmaydi.

**How to apply:**
- Ishni boshlashdan oldin `git branch --show-current` va `git status` bilan tekshir: boshqa agent branch'ni almashtirgan yoki fayl yozgan bo'lishi mumkin.
- Har bir agent ishidan keyin `git diff` / `git log` bilan tekshirish kerak.
- Commit va push faqat foydalanuvchi so'raganda qilinadi.
- Repo public, shuning uchun bu vault notalari (`references/`, `MEMORY.md`) ham push qilinsa hammaga ko'rinadi.
- Private qilish buyrug'i: `gh repo edit mcodevs/music_lab --visibility private --accept-visibility-change-consequences`.

Bog'liq: [[refaktoring-review]], [[video-optimize]], [[workspace-tozalandi]], [[music-toolkit]]
