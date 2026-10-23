# Dark Souls Remastered for Mac

[English](#english) · [Français](#français)

## English

Play **your own copy** of DARK SOULS: REMASTERED (Nintendo Switch, update 1.0.3) natively on an Apple silicon Mac,
at 60, 90 or 120 fps and at 1080p, 1440p or 4K. It is not an emulator: the game's own ARM64 code runs on the Apple
chip (rewritten where macOS requires it), a small host answers the Switch system calls, and the graphics are rebuilt
on Metal. It runs on [nxnative](https://github.com/seedds/nxnative).

**Nothing from the game is in this repository.** You bring your dump; `install.sh` builds the app on your Mac from it.
The app you build contains the game: it is for your own use, do not share it. This project is not affiliated with,
endorsed or sponsored by Bandai Namco Entertainment, FromSoftware or Nintendo. DARK SOULS is a trademark of Bandai
Namco Entertainment Inc.; Nintendo Switch is a trademark of Nintendo.

### What you need

- A Mac with Apple silicon (M1 or later) and **macOS 26 or later**. 16 GB of memory recommended for 4K.
- About **10 GB** free during the build, 5.5 GB for the app afterwards.
- Your game, dumped from **your own Switch** (for example with DBI or nxdumptool): the base game (NSP or XCI)
  **and the 1.0.3 update** (v196608, NSP), plus **`prod.keys`** dumped from the same console (Lockpick_RCM).
  Only update 1.0.3 is supported; `install.sh` checks every file and refuses anything else.
- Xcode (for the Metal compiler and `swiftc`): after installing it, run `xcodebuild -downloadComponent MetalToolchain`.
- [Homebrew](https://brew.sh), then:
  ```
  brew install spirv-cross git
  brew install --cask dotnet-sdk
  python3 -m pip install lz4 capstone numpy pillow scipy etcpak
  ```

### Install

```
git clone https://github.com/MeNass89/dsr-mac.git dsr-mac && cd dsr-mac
./install.sh --nsp-base "DARK SOULS REMASTERED [01004AB00A260000][v0].nsp" \
             --nsp-update "DARK SOULS REMASTERED [01004AB00A260800][v196608].nsp" \
             --keys ~/keys/prod.keys
```

If you already extracted the game (a folder with `ExeFS/` and `RomFS/`, base and update merged):
`./install.sh --dump <folder>`.

The app lands in `~/Applications/Dark Souls Remastered.app` (`--out` to change it). The first build takes
30 to 90 minutes, most of it compiling about 3,100 shaders; `--modes "60 4k60"` builds only the modes you want.
`./install.sh --help` lists every option.

**First launch:** the app is signed ad hoc, not by an identified developer. Right-click the app → **Open**, then
**Open** again (once). If macOS still refuses: System Settings → Privacy & Security → **Open Anyway**.

### Settings

The launcher window opens before the game (hold **⌥ Option** at launch to see it again if you chose to skip it).

- **Graphics:** internal resolution 1080p / 1440p / 4K, frame rate 60 / 90 / 120, window or fullscreen
  (⌘F in game), Metal performance overlay. The game keeps normal speed below the chosen rate.
- **Controls:** any controller macOS knows (Xbox, PlayStation, Switch Pro), buttons by position or by label.
  Keyboard: WASD move, arrows D-pad, J/K/U/I = A/B/X/Y, Q/E = L/R, Z/C = ZL/ZR, Return = +, Tab = −. ⌘Q quits.
- **Button prompts** (Controls): Auto / Switch / PlayStation / Xbox. The buttons drawn in the game's menus and
  messages match your controller: Auto picks PlayStation or Xbox pictures from the controller connected when you
  press Play (Switch letters with the keyboard or a Switch controller). They follow the face-button setting, so the
  picture always names the button that does the action. `install.sh` draws these sets from your own game files
  (it needs `numpy pillow scipy etcpak`; without them, only the Switch letters are available).
- **Textures** (Graphics, optional): Switch or PC. See *PC textures* below.
- **Audio:** volume.
- **Mods:** drop a mod folder (UXM layout: `chr/`, `parts/`, `map/`, `msg/`, `param/`…) into the Mods pane; it
  replaces files the game already has. Back up your save first.
- **Saves:** `~/Library/Application Support/nxnative/DarkSoulsRemastered/save`, with a backup button.

### PC textures (optional)

If you also own the PC version of DARK SOULS: REMASTERED, the app can use its textures wherever they are sharper
than the Switch ones (up to 4× the pixels, BC7 colour, BC5 normal maps). Add your PC game folder (the one with
`chr/`, `map/`, `parts/`) to the build:

```
./install.sh --dump <folder> --pc-game "<PC game folder>"
```

It takes about 16 more minutes, adds **2.7 GB** to the app and needs
`python3 -m pip install numpy pillow etcpak texture2ddecoder`. Nothing from the PC game ships here either: the
textures are converted from your copy on your Mac. Then choose **Graphics → Textures → PC** in the launcher. It uses
more memory and disk; Switch stays the default.

### Known issues

- **First load can hang.** About 1 launch in 17 at 60 fps, the game stays on the loading screen after
  *Continue*. Quit (⌘Q) and launch again. It is more likely when the Mac is busy with other heavy work.
- **120 fps** needs a 120 Hz display (MacBook Pro ProMotion, or an external 120 Hz screen); on a 60 Hz screen the
  extra frames are not shown. **1440p and 4K at 120 fps** do not hold 120 on most Macs (4K at 120 runs at about 105 fps
  on an M4 Pro); 60 or 90 fps is the better choice there.
- **The first launch of a freshly built app can be slow:** it can take several minutes before the window appears
  while macOS checks the new 5 GB bundle once (measured up to 16 minutes on a busy MacBook Air, external disk).
  Later launches start at once.
- **Short stutters** the first time a new effect appears: the app compiles it once and remembers it.
- Online play, messages and summon signs from other players are not available (offline only).
- Tested on an M4 Pro MacBook Pro and an M2 MacBook Air, macOS 27.2. Other Macs should work but are not verified.

When something goes wrong, the log of the last run is in About (`last-run.log`).

### Credits

- **[nxnative](https://github.com/seedds/nxnative)** by seedds (MIT), which runs Switch games natively on Apple
  chips, itself built on **[d2r-mobile](https://github.com/jhaizhou-ops/d2r-mobile)** (MIT) by jhaizhou. The Dark
  Souls Remastered bring-up (SDK 4 support, 60/90/120 fps and 1440p/4K cuts, present, audio, mods overlay) was done
  on the fork [MeNass89/nxnative](https://github.com/MeNass89/nxnative), branch `dsr-bringup`.
- **Ryujinx** (MIT): shader translator. **SPIRV-Cross** (Apache 2.0). **LibHac** (MIT) reads your NSPs.
  **libvpx**, **stb_vorbis**, **libdeflate**, **deko3d** and the other components listed in nxnative's
  `dm/third_party/README.md`, each under its own license.
- **[MacNativeGames](https://github.com/ly05010419/MacNativeGames)** (MIT): parts of the host adapted from it, and the
  model for a build-from-your-own-dump release.
- **masagrator** (FPSLocker-Warehouse) for the 1.0.3 frame-rate addresses.

License: the scripts and launcher in this repository are MIT (see `LICENSE`). nxnative and third-party code keep
their own licenses.

---

## Français

Jouez à **votre propre exemplaire** de DARK SOULS: REMASTERED (Nintendo Switch, mise à jour 1.0.3) en natif sur un
Mac Apple silicon, à 60, 90 ou 120 images/s et en 1080p, 1440p ou 4K. Ce n'est pas un émulateur : le code ARM64 du
jeu tourne directement sur la puce Apple (réécrit là où macOS l'exige), un petit hôte répond aux appels système de la
Switch, et le rendu est reconstruit sur Metal. Le portage repose sur [nxnative](https://github.com/seedds/nxnative).

**Ce dépôt ne contient rien du jeu.** Vous apportez votre dump ; `install.sh` construit l'application sur votre Mac
à partir de lui. L'application obtenue contient le jeu : elle est pour votre usage personnel, ne la partagez pas. Ce
projet n'est ni affilié, ni approuvé, ni soutenu par Bandai Namco Entertainment, FromSoftware ou Nintendo. DARK SOULS
est une marque de Bandai Namco Entertainment Inc. ; Nintendo Switch est une marque de Nintendo.

### Il vous faut

- Un Mac Apple silicon (M1 ou plus récent) sous **macOS 26 ou plus récent**. 16 Go de mémoire conseillés pour la 4K.
- Environ **10 Go** libres pendant la construction, 5,5 Go pour l'application ensuite.
- Votre jeu, extrait de **votre propre Switch** (par exemple avec DBI ou nxdumptool) : le jeu de base (NSP ou XCI)
  **et la mise à jour 1.0.3** (v196608, NSP), plus le fichier **`prod.keys`** de la même console (Lockpick_RCM).
  Seule la 1.0.3 est prise en charge ; `install.sh` vérifie chaque fichier et refuse tout le reste.
- Xcode (pour le compilateur Metal et `swiftc`) ; une fois installé, lancez `xcodebuild -downloadComponent MetalToolchain`.
- [Homebrew](https://brew.sh), puis :
  ```
  brew install spirv-cross git
  brew install --cask dotnet-sdk
  python3 -m pip install lz4 capstone numpy pillow scipy etcpak
  ```

### Installation

```
git clone https://github.com/MeNass89/dsr-mac.git dsr-mac && cd dsr-mac
./install.sh --nsp-base "DARK SOULS REMASTERED [01004AB00A260000][v0].nsp" \
             --nsp-update "DARK SOULS REMASTERED [01004AB00A260800][v196608].nsp" \
             --keys ~/keys/prod.keys
```

Si le jeu est déjà extrait (un dossier avec `ExeFS/` et `RomFS/`, base et mise à jour fusionnées) :
`./install.sh --dump <dossier>`.

L'application arrive dans `~/Applications/Dark Souls Remastered.app` (`--out` pour changer). La première construction
prend 30 à 90 minutes, surtout pour compiler environ 3 100 shaders ; `--modes "60 4k60"` ne construit que les modes
voulus. `./install.sh --help` liste toutes les options.

**Premier lancement :** l'application est signée « ad hoc », pas par un développeur identifié. Clic droit sur
l'application → **Ouvrir**, puis **Ouvrir** (une seule fois). Si macOS refuse encore : Réglages Système →
Confidentialité et sécurité → **Ouvrir quand même**.

### Réglages

La fenêtre du lanceur s'ouvre avant le jeu (maintenez **⌥ Option** au lancement pour la revoir si vous l'avez masquée).

- **Graphismes :** résolution interne 1080p / 1440p / 4K, 60 / 90 / 120 images/s, fenêtre ou plein écran (⌘F en
  jeu), surcouche de performance Metal. Sous le taux choisi, le jeu garde sa vitesse normale.
- **Commandes :** toute manette reconnue par macOS (Xbox, PlayStation, Switch Pro), boutons par position ou par
  étiquette. Clavier : ZQSD/WASD selon la disposition pour bouger, flèches = croix, J/K/U/I = A/B/X/Y, Q/E = L/R,
  Z/C = ZL/ZR, Entrée = +, Tab = −. ⌘Q pour quitter.
- **Icônes des boutons** (Commandes) : Auto / Switch / PlayStation / Xbox. Les boutons dessinés dans les menus et
  messages du jeu correspondent à votre manette : Auto choisit les dessins PlayStation ou Xbox d'après la manette
  branchée au moment de Jouer (lettres Switch au clavier ou avec une manette Switch). Ils suivent le réglage des
  boutons de façade : le dessin nomme toujours le bouton qui fait l'action. `install.sh` dessine ces jeux d'icônes à
  partir de vos propres fichiers du jeu (il faut `numpy pillow scipy etcpak` ; sans eux, seules les lettres Switch
  sont disponibles).
- **Textures** (Graphismes, optionnel) : Switch ou PC. Voir *Textures PC* plus bas.
- **Audio :** volume.
- **Mods :** déposez un dossier de mod (disposition UXM : `chr/`, `parts/`, `map/`, `msg/`, `param/`…) dans le
  panneau Mods ; il remplace des fichiers que le jeu possède déjà. Sauvegardez d'abord.
- **Sauvegardes :** `~/Library/Application Support/nxnative/DarkSoulsRemastered/save`, avec un bouton de copie.

### Textures PC (optionnel)

Si vous possédez aussi la version PC de DARK SOULS: REMASTERED, l'application peut utiliser ses textures partout où
elles sont plus nettes que celles de la Switch (jusqu'à 4× les pixels, couleur BC7, normales BC5). Ajoutez le dossier
du jeu PC (celui qui contient `chr/`, `map/`, `parts/`) à la construction :

```
./install.sh --dump <dossier> --pc-game "<dossier du jeu PC>"
```

Comptez environ 16 minutes de plus et **2,7 Go** de plus pour l'application ; il faut
`python3 -m pip install numpy pillow etcpak texture2ddecoder`. Rien du jeu PC n'est fourni ici non plus : les textures
sont converties depuis votre copie, sur votre Mac. Choisissez ensuite **Graphismes → Textures → PC** dans le lanceur.
Cela utilise plus de mémoire et de disque ; Switch reste le réglage par défaut.

### Problèmes connus

- **Le premier chargement peut se bloquer.** Environ 1 lancement sur 17 à 60 images/s, le jeu reste sur l'écran de
  chargement après *Continuer*. Quittez (⌘Q) et relancez. C'est plus fréquent quand le Mac est très occupé par ailleurs.
- **120 images/s** demande un écran 120 Hz (MacBook Pro ProMotion ou écran externe 120 Hz) ; sur un écran 60 Hz les
  images en plus ne s'affichent pas. **1440p et 4K à 120** ne tiennent pas 120 sur la plupart des Mac (la 4K à 120 tourne
  à environ 105 images/s sur un M4 Pro) ; préférez 60 ou 90.
- **Le premier lancement d'une application fraîchement construite peut être lent :** plusieurs minutes avant que la
  fenêtre n'apparaisse, le temps que macOS vérifie une fois la nouvelle application de 5 Go (jusqu'à 16 minutes mesurées
  sur un MacBook Air chargé, disque externe). Les lancements suivants sont immédiats.
- **Petits à-coups** la première fois qu'un nouvel effet apparaît : l'application le compile une fois et s'en souvient.
- Pas de jeu en ligne, ni messages ni signes d'invocation d'autres joueurs (hors ligne uniquement).
- Testé sur MacBook Pro M4 Pro et MacBook Air M2, macOS 27.2. Les autres Mac devraient fonctionner sans être vérifiés.

En cas de problème, le journal du dernier lancement est dans À propos (`last-run.log`).

### Remerciements

- **[nxnative](https://github.com/seedds/nxnative)** de seedds (MIT), qui fait tourner les jeux Switch en natif sur
  puce Apple, lui-même issu de **[d2r-mobile](https://github.com/jhaizhou-ops/d2r-mobile)** (MIT) de jhaizhou. Le
  portage de Dark Souls Remastered (prise en charge du SDK 4, découpes 60/90/120 i/s et 1440p/4K, présentation,
  audio, surcouche de mods) a été fait sur le fork [MeNass89/nxnative](https://github.com/MeNass89/nxnative), branche
  `dsr-bringup`.
- **Ryujinx** (MIT) : traducteur de shaders. **SPIRV-Cross** (Apache 2.0). **LibHac** (MIT) lit vos NSP.
  **libvpx**, **stb_vorbis**, **libdeflate**, **deko3d** et les autres composants listés dans
  `dm/third_party/README.md` de nxnative, chacun sous sa licence.
- **[MacNativeGames](https://github.com/ly05010419/MacNativeGames)** (MIT) : des parties de l'hôte en viennent, et
  le modèle d'une publication « construisez depuis votre propre dump ».
- **masagrator** (FPSLocker-Warehouse) pour les adresses de cadence de la 1.0.3.

Licence : les scripts et le lanceur de ce dépôt sont sous MIT (voir `LICENSE`). nxnative et le code tiers gardent
leurs propres licences.
