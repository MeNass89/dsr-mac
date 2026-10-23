"""Pack a mod folder (archive-path layout) into the launcher's texture pack: textures.append (files back to back, 16-aligned) + textures.index
(one line per file: archive 0|1, path hash hex, offset in textures.append, size, path). The launcher clones textures.append into the overlay
(APFS clone, no copy), points the index entries past the archive's end and appends the other mods after it.
usage: python -I pack.py <RomFS> <mod dir> <pack dir>"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fsfmt import fs_hash, bhd5_entries

def pack(romfs, mod, out):
    idx = [bhd5_entries(f'{romfs}/dvdbnd{a}.bhd5') for a in (0, 1)]
    os.makedirs(out, exist_ok=True); off = 0; lines = []
    with open(os.path.join(out, 'textures.append.tmp'), 'wb') as f:
        for root, _, files in sorted(os.walk(mod)):
            for fn in sorted(files):
                rel = '/' + os.path.relpath(os.path.join(root, fn), mod); h = fs_hash(rel)
                a = next((a for a in (0, 1) if h in idx[a]), None)
                if a is None: print('not in the game index:', rel); continue
                data = open(os.path.join(root, fn), 'rb').read()
                pad = (-off) % 16; f.write(b'\0' * pad); off += pad
                f.write(data); lines.append(f'{a}\t{h:08x}\t{off}\t{len(data)}\t{rel}'); off += len(data)
    open(os.path.join(out, 'textures.index'), 'w').write('\n'.join(lines) + '\n')
    os.replace(os.path.join(out, 'textures.append.tmp'), os.path.join(out, 'textures.append'))
    print(len(lines), 'files', off, 'bytes')

if __name__ == '__main__': pack(*sys.argv[1:4])
