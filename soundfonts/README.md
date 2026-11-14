# SoundFont: FluidR3_GM.sf2

MIDI → audio render (fluidsynth, `voice-to-music` skill) uchun General MIDI SoundFont kerak:
`soundfonts/FluidR3_GM.sf2` (148 MB). Fayl **git'da saqlanmaydi**, chunki GitHub 100 MB dan
katta faylni qabul qilmaydi (`.gitignore` da `soundfonts/*`). Yangi kompyuterda yoki repo
klonlangandan keyin uni bir marta yuklab qo'yish kerak.

## 1-usul: skript bilan (tavsiya)

Loyiha papkasida:

```bash
sh scripts/get_soundfont.sh
```

Skript:
- rasmiy Debian paketini yuklaydi: `fluid-soundfont-gm_3.1-6_all.deb`, ~120 MB,
  `deb.debian.org` dan;
- ichidan `FluidR3_GM.sf2` ni ajratib oladi (macOS'dagi `tar` bilan, qo'shimcha dastur kerak emas);
- SHA-256 ni tekshiradi va faylni `soundfonts/` ga qo'yadi.

Fayl allaqachon joyida va butun bo'lsa, skript hech narsa yuklamaydi. Qayta yuklash kerak bo'lsa:
`sh scripts/get_soundfont.sh --force`.

Internet sekin bo'lsa (masalan, iPhone hotspot), 120 MB yuklash bir necha daqiqa oladi. Uzilib
qolsa, skriptni qayta ishga tushiring.

## 2-usul: qo'lda

1. Paketni brauzerda yuklab oling:
   https://deb.debian.org/debian/pool/main/f/fluid-soundfont/fluid-soundfont-gm_3.1-6_all.deb
2. Terminalda (Downloads papkasida):
   ```bash
   tar -xf fluid-soundfont-gm_3.1-6_all.deb data.tar.xz && tar -xf data.tar.xz ./usr/share/sounds/sf2/FluidR3_GM.sf2
   ```
3. `usr/share/sounds/sf2/FluidR3_GM.sf2` ni loyihadagi `soundfonts/` papkasiga ko'chiring.
4. Tekshiring: natija quyidagi qatorga mos kelishi kerak.
   ```bash
   shasum -a 256 soundfonts/FluidR3_GM.sf2
   ```
   `74594e8f4250680adf590507a306655a299935343583256f3b722c48a1bc1cb0`

## Ishlatish

fluidsynth Homebrew orqali o'rnatiladi (`brew install fluid-synth`). Render qilish:

```bash
fluidsynth -ni -q -g 0.8 -r 44100 -F out.wav soundfonts/FluidR3_GM.sf2 in.mid
```

## Litsenziya

FluidR3_GM (Frank Wen) MIT litsenziyasi ostida tarqatiladi (Debian paketidagi `copyright` fayli).
