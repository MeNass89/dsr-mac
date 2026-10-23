#!/bin/zsh
# Dark Souls Remastered for Mac: build the app from YOUR OWN legally dumped copy of the Switch game (update 1.0.3).
# Nothing from the game ships with this script. It checks your files against known hashes, rewrites the game's code for macOS (nxnative),
# translates its shaders to Metal, builds the host and the launcher, and assembles "Dark Souls Remastered.app" on this Mac.
#
#   ./install.sh --nsp-base <base .nsp|.xci> --nsp-update <v196608 update .nsp> --keys <prod.keys> [--out <app path>]
#   ./install.sh --dump <folder with ExeFS/ and RomFS/ of 1.0.3, base+update merged> [--out <app path>]
#
# Options: --out <path.app>       (default ~/Applications/Dark Souls Remastered.app)
#          --work <dir>           work folder, ~10 GB, on the same APFS volume as --out to clone the RomFS for free (default ~/Library/Caches/dsr-mac-build)
#          --nxnative <dir>       an existing nxnative checkout at the pinned commit (default: cloned into the work folder)
#          --modes "60 2k60 ..."  which frame rate / resolution builds to make (default: all nine)
#          --quick                check file sizes instead of SHA-256 of the 3.6 GB archives
#          --keep-work            keep the work folder (default: removed after success, except the shader cache)
#          (PlayStation / Xbox button prompts are built when Python has numpy pillow scipy etcpak)
#          --pc-game <dir>        optional: your PC copy of Dark Souls Remastered (the folder with chr/ map/ parts/): builds the
#                                 "Textures: PC" option from it (PC textures where sharper, ~16 min, +2.7 GB). Needs numpy pillow etcpak texture2ddecoder.
set -e
setopt pipefail
HERE=${0:A:h}
TITLE=01004AB00A260000
NX_REPO=${NX_REPO:-https://github.com/MeNass89/nxnative.git}
NX_COMMIT=${NX_COMMIT:-6552b528a51c4920d9df60ac88adf1181f3ddb18}
CHAIN=e74e5b975ca2
OUT="$HOME/Applications/Dark Souls Remastered.app"; WORK="$HOME/Library/Caches/dsr-mac-build"
MODES=(60 90 120 2k60 2k90 2k120 4k60 4k90 4k120); QUICK=0; KEEP=0; DUMP=; BASE=; UPD=; KEYS=; NX=; PCG=
while (( $# )); do case $1 in
  --dump) DUMP=${2:A}; shift 2;; --nsp-base) BASE=${2:A}; shift 2;; --nsp-update) UPD=${2:A}; shift 2;; --keys) KEYS=${2:A}; shift 2;;
  --out) OUT=${2:A}; [[ $OUT == *.app ]] || OUT="$OUT/Dark Souls Remastered.app"; shift 2;; --work) WORK=${2:A}; shift 2;; --nxnative) NX=${2:A}; shift 2;; --modes) MODES=(${=2}); shift 2;;
  --pc-game) PCG=${2:A}; shift 2;;
  --quick) QUICK=1; shift;; --keep-work) KEEP=1; shift;; -h|--help) sed -n 2,17p "$0" | sed 's/^# \{0,1\}//'; exit 0;;
  *) echo "unknown option $1 (see --help)"; exit 2;; esac; done
T0=$SECONDS
say() { printf '[%3ds] %s\n' $((SECONDS - T0)) "$*"; }
die() { printf '\n[FAILED] %s\n' "$*" >&2; exit 1; }
LOGS="$WORK/logs"; mkdir -p "$LOGS"
logrun() { local log=$LOGS/$1.log; shift; "$@" > "$log" 2>&1 || { tail -20 "$log" >&2; die "$1 failed (full log: $log)"; }; }
expect() { awk -F'\t' -v k="$1" -v p="$2" '$1==k && $2==p {print $'"${3:-4}"'}' "$HERE/expected.tsv"; }

# ---- 1. requirements ----
say "1/9 checking this Mac"
[ "$(uname -m)" = arm64 ] || die "Apple silicon (M1 or later) is required"
[ "$(sw_vers -productVersion | cut -d. -f1)" -ge 26 ] || die "macOS 26 or later is required (this Mac: $(sw_vers -productVersion))"
xcrun -sdk macosx metal --version >/dev/null 2>&1 || die "the Metal compiler is missing: install Xcode, then run: xcodebuild -downloadComponent MetalToolchain"
command -v swiftc >/dev/null || die "swiftc is missing: install Xcode"
command -v spirv-cross >/dev/null || die "spirv-cross is missing: brew install spirv-cross"
PY=${PYTHON:-python3}
$PY -c 'import lz4.block, capstone' 2>/dev/null || die "Python needs lz4 and capstone: $PY -m pip install lz4 capstone"
DOTNET=$(command -v dotnet || ls $HOME/.dotnet/dotnet /usr/local/share/dotnet/dotnet 2>/dev/null | head -1 || true)
[ -n "$DOTNET" ] && "$DOTNET" --list-runtimes 2>/dev/null | grep -q 'Microsoft.NETCore.App 10\.' || die ".NET 10 is missing (the shader translator runs on it): brew install --cask dotnet-sdk"
export DOTNET_ROOT=${DOTNET_ROOT:-${DOTNET:h}} PATH="${DOTNET:h}:$PATH"
[ -n "$DUMP" ] || [ -n "$BASE" ] || die "give your game: --nsp-base/--nsp-update/--keys, or --dump (see --help)"
FREE=$(df -g "$WORK" | awk 'NR==2{print $4}'); [ "$FREE" -ge 8 ] || die "need about 8 GB free in $WORK (have ${FREE} GB)"

# ---- 2. nxnative (MIT) at the commit these hashes were made with ----
say "2/9 nxnative $NX_COMMIT"
if [ -z "$NX" ]; then NX=$WORK/nxnative
  [ -d "$NX/.git" ] || git clone -q "$NX_REPO" "$NX"
  git -C "$NX" fetch -q origin "$NX_COMMIT" 2>/dev/null || true; git -C "$NX" checkout -q --detach "$NX_COMMIT"
fi
[ "$(git -C "$NX" rev-parse HEAD)" = "$NX_COMMIT" ] || die "$NX is not at $NX_COMMIT (patched-code hashes depend on it)"

# ---- 3. your game files ----
EX=$WORK/extract
if [ -n "$BASE" ]; then
  say "3/9 extracting your NSPs (LibHac)"
  [ -f "$BASE" ] && [ -f "$UPD" ] && [ -f "$KEYS" ] || die "--nsp-base, --nsp-update and --keys must all be files"
  logrun nx_extract_build "$DOTNET" build "$NX/dm/tools/nx_extract" -c Release -o "$WORK/tools/nx_extract" -v quiet -nologo
  rm -rf "$EX"; logrun nx_extract "$WORK/tools/nx_extract/nx_extract" "$KEYS" "$BASE" "$UPD" "$EX"
  DUMP=$EX
else say "3/9 using your extracted dump $DUMP"; fi
[ -d "$DUMP/ExeFS" ] && [ -d "$DUMP/RomFS" ] || die "$DUMP must hold ExeFS/ and RomFS/"

# ---- 4. version check: only DARK SOULS: REMASTERED 1.0.3 (v196608) is supported ----
say "4/9 checking your files are the 1.0.3 update ($([ $QUICK = 1 ] && echo sizes || echo SHA-256))"
bad=()
while IFS=$'\t' read -r kind p size sha; do
  case $kind in exefs) f=$DUMP/ExeFS/$p;; romfs) f=$DUMP/RomFS/$p;; *) continue;; esac
  [ -f "$f" ] || { bad+=("missing $kind/$p"); continue; }
  [ "$(stat -f %z "$f")" = "$size" ] || { bad+=("$kind/$p: size $(stat -f %z "$f"), expected $size"); continue; }
  if [ $QUICK = 0 ] || [ "$kind" = exefs ]; then [ "$(shasum -a 256 "$f" | cut -d' ' -f1)" = "$sha" ] || bad+=("$kind/$p: SHA-256 differs"); fi
done < <(grep -v '^#' "$HERE/expected.tsv")
(( ${#bad} == 0 )) || die "these are not the files of DARK SOULS: REMASTERED 1.0.3 (base + update v196608):"$'\n  '"${(j:\n  :)bad}"

# ---- 5. game profile and shader tables, made from your files ----
say "5/9 game profile and shader tables"
GP=$WORK/profile/$TITLE; rm -rf "$GP"; mkdir -p "$GP"
cp "$HERE/profile/$TITLE/"* "$GP/"
export DM_GAMES_DIR=$WORK/profile DM_GAMES_FIRST=1 DM_GAME=$TITLE DM_ROOT=$WORK J=${J:-$(sysctl -n hw.ncpu)}
mkdir -p "$WORK/tmp"; TOOLENV=(WORK=$WORK/tmp)   # the tools' temporary folder (not exported: $WORK is ours)
V=$WORK/ver/v196608; rm -rf "$V"; mkdir -p "$V"; ln -s "$DUMP/RomFS" "$V/RomFS"
logrun glslc $PY "$HERE/tools/dsr_glslc.py" "$DUMP/RomFS" "$V/glslc_capture"     # the ~3,000 shaders kept in the game archives
rm -rf "$WORK/shader/pkg"; mkdir -p "$WORK/shader"
logrun shader_split env $TOOLENV $PY "$NX/dm/gfx/tools/shader_split.py" "$V/RomFS" "$DUMP/ExeFS/main" "$WORK/shader/pkg" "$GP/shader_map.tsv" "$GP/shader_facts.tsv" "$GP/shader_pairs.tsv"
for t in shader_map.tsv shader_facts.tsv shader_pairs.tsv; do
  [ "$(grep -v '^#' "$GP/$t" | shasum -a 256 | cut -d' ' -f1)" = "$(expect table $t)" ] || die "the shader table $t made from your files differs from the verified one"
done
logrun chain $PY "$NX/dm/gfx/tools/dmsh_chain.py" --header
[ "$(cat "$LOGS/chain.log")" = "$CHAIN" ] || die "shader chain version $(cat "$LOGS/chain.log"), expected $CHAIN (translator, spirv-cross or Metal compiler differ: see $LOGS)"
$PY "$NX/dm/gfx/tools/dmsh_chain.py" --check-tools > "$LOGS/check_tools.log" 2>&1 || die "shader tools do not match nxnative's lock file (Xcode or spirv-cross version): $(head -3 "$LOGS/check_tools.log")"

# ---- 6. the game's code, rewritten for macOS (one build per frame rate / resolution) ----
say "6/9 rewriting the game code: ${#MODES} modes"
PT=$WORK/patched; rm -rf "$PT"; mkdir -p "$PT/common"
for m in sdk subsdk0; do logrun patch_$m env DM_RULESET=native $PY "$NX/dm/tools/patch_nso.py" "$DUMP/ExeFS/$m" "$PT/common" $m; done
for m in sdk subsdk0; do [ "$(shasum -a 256 "$PT/common/$m.patched.bin" | cut -d' ' -f1)" = "$(expect patched all/$m.patched.bin)" ] || die "rewritten $m differs from the verified build"; done
PJ=${PJ:-3}; pids=()   # main rewrites in parallel, PJ at a time (each takes 2-3 min and ~1 GB)
for mode in $MODES; do
  fps=${mode#*k}; res=; [[ $mode == 2k* ]] && res=1440; [[ $mode == 4k* ]] && res=2160; d=$PT/main$mode
  [[ $fps == (60|90|120) ]] || die "unknown mode $mode (60 90 120 2k60 2k90 2k120 4k60 4k90 4k120)"
  mkdir -p "$d"; cp "$PT/common/"* "$d/"
  env DM_RULESET=native DM_DSR_FPS=$fps ${res:+DM_DSR_RES=$res} $PY "$NX/dm/tools/patch_nso.py" "$DUMP/ExeFS/main" "$d" main > "$LOGS/patch_main$mode.log" 2>&1 &
  pids+=($!); (( ${#pids} < PJ )) || { wait $pids[1] || true; pids=(${pids[2,-1]}); }
done
wait || true
for mode in $MODES; do d=$PT/main$mode
  [ "$(shasum -a 256 "$d/main.patched.bin" 2>/dev/null | cut -d' ' -f1)" = "$(expect patched main$mode/main.patched.bin)" ] || { tail -5 "$LOGS/patch_main$mode.log" >&2; die "rewritten main ($mode) is missing or differs from the verified build (log: $LOGS/patch_main$mode.log)"; }
done

# ---- 7. shaders: Switch GPU code → SPIR-V → Metal, compiled on this Mac ----
say "7/9 translating and compiling ~3,100 shaders (5-20 min the first time; cached after)"
logrun dmsh_build env $TOOLENV $PY "$NX/dm/gfx/tools/dmsh_build.py" "$WORK/shader/pkg" "$WORK/shader/cache"
logrun c1_guard $PY "$NX/dm/gfx/tools/c1_guard.py" "$WORK/shader/cache/b-$CHAIN" "$GP/c1_full.tsv"
n=$(ls "$WORK/shader/cache/b-$CHAIN" | grep -c '_b.metallib$' || true); [ "$n" -ge 3000 ] || die "only $n shader libraries built (see $LOGS/dmsh_build.log)"

# ---- 8. host and launcher ----
say "8/9 building the host (dmhost) and the launcher"
logrun dmhost make -C "$NX/dm/host" -j"$J" GAME=$TITLE dmhost
logrun launcher swiftc -O -parse-as-library "$HERE/launcher/Launcher.swift" -o "$WORK/DarkSouls"

# ---- 9. the app ----
say "9/9 assembling $OUT"
rm -rf "$OUT"; R="$OUT/Contents/Resources/game"; mkdir -p "$OUT/Contents/MacOS" "$R/games/$TITLE"
cp "$NX/dm/host/dmhost" "$WORK/DarkSouls" "$OUT/Contents/MacOS/"
for mode in $MODES; do cp -c -R "$PT/main$mode" "$R/main$mode" 2>/dev/null || cp -R "$PT/main$mode" "$R/main$mode"; done
cp -c -R "$WORK/shader/cache" "$R/msl" 2>/dev/null || cp -R "$WORK/shader/cache" "$R/msl"
cp -c -R "$DUMP/RomFS" "$R/romfs" 2>/dev/null || { say "   (RomFS on another volume: copying 3.8 GB)"; cp -R "$DUMP/RomFS" "$R/romfs"; }
cp "$GP"/*.tsv "$GP/dmsh_chain.h" "$R/games/$TITLE/"
if [ -n "$PCG" ]; then   # PC textures from the user's PC copy (never shipped): rebuilt Switch archives + index, read by the launcher
  [ -d "$PCG/chr" ] && [ -d "$PCG/map" ] || die "--pc-game: $PCG must hold chr/ and map/ (the PC game folder)"
  $PY -c 'import numpy, PIL, etcpak, texture2ddecoder' 2>/dev/null || die "PC textures need: $PY -m pip install numpy pillow etcpak texture2ddecoder"
  say "   PC textures from $PCG (about 16 min)"
  logrun pctex_convert env DSR_PCTEX_NORMALS=bc7 $PY -I "$HERE/tools/dsr-pc-textures/convert.py" "$DUMP/RomFS" "$PCG" "$WORK/pctex-mod" --workers 6
  logrun pctex_pack $PY -I "$HERE/tools/dsr-pc-textures/pack.py" "$DUMP/RomFS" "$WORK/pctex-mod" "$R/pctextures"
  rm -rf "$WORK/pctex-mod"
fi
# Button pictures for PlayStation / Xbox controllers (Settings > Controls > Button prompts): the game's own font and menu archives,
# redrawn from your RomFS (nothing shipped). Optional: skipped with a note when the Python modules are missing (Switch prompts only).
if $PY -c 'import numpy, PIL, scipy, etcpak' 2>/dev/null; then
  say "   button prompts (PlayStation / Xbox sets, about 10 min)"
  rm -rf "$WORK/glyphs"; logrun glyphs $PY -I "$HERE/tools/dsr-glyphs/dsr_glyphs.py" "$DUMP/RomFS" "$WORK/glyphs"
  mkdir -p "$R/glyphs"; for g in ps-position ps-label xbox-position xbox-label; do
    [ -d "$WORK/glyphs/$g" ] || die "button prompt set $g was not built (log: $LOGS/glyphs.log)"; cp -R "$WORK/glyphs/$g" "$R/glyphs/$g"; done
  rm -rf "$WORK/glyphs"
else say "   button prompts skipped (Switch letters only): $PY -m pip install numpy pillow scipy etcpak, then run again"; fi
[ -f "$DUMP/../icon.jpg" ] && ICON=$DUMP/../icon.jpg || ICON=$DUMP/icon.jpg
[ -f "$ICON" ] && sips -s format icns "$ICON" --out "$OUT/Contents/Resources/AppIcon.icns" >/dev/null 2>&1 || true
cat > "$OUT/Contents/Info.plist" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleName</key><string>Dark Souls Remastered</string>
<key>CFBundleDisplayName</key><string>Dark Souls Remastered</string>
<key>CFBundleIdentifier</key><string>org.nxnative.01004ab00a260000</string>
<key>CFBundleExecutable</key><string>DarkSouls</string>
<key>CFBundleIconFile</key><string>AppIcon</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>1.0.3</string>
<key>LSApplicationCategoryType</key><string>public.app-category.games</string>
<key>LSMinimumSystemVersion</key><string>26.0</string>
<key>NSHighResolutionCapable</key><true/>
<key>GCSupportsControllerUserInteraction</key><true/>
</dict></plist>
PL
codesign --force --deep -s - "$OUT" > "$LOGS/codesign.log" 2>&1 || say "   ad-hoc signing failed (see $LOGS/codesign.log); the app may still open with right-click > Open"
# Settings the launcher reads: the 120 fps build needs a 120 Hz display; nothing else to configure
[ $KEEP = 1 ] || rm -rf "$PT" "$WORK/shader/pkg" "$WORK/tmp" "$WORK/ver" "$EX"
say "done: $OUT ($(du -sh "$OUT" | cut -f1)); saves go to ~/Library/Application Support/nxnative/DarkSoulsRemastered"
