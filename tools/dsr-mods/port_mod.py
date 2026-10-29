"""Port a Dark Souls Remastered PC mod to the Switch files the Mac app runs.
usage: python3 -I port_mod.py <mod folder> <RomFS> <out folder>
The PC files of a Nexus mod do not load on the Switch build: archives use other flags and names (BND3 64-bit offsets, INTERROOT_ns64), textures are
Tegra block-linear with an NVN header, and whole files carry PC-only content. Each mod file is merged into the matching Switch file instead:
  msg/<LANG>/*.msgbnd.dcx    text tables: every entry the mod changes, by id, into the Switch tables (FMG)
  param/**/*.parambnd.dcx    params: rows the mod changes, by row id, into the Switch params (same row layout required)
  map/mXX/mXX_000N/*.dds     map textures (TPUP layout): into the Switch mXX_000N.tpfbhd/.tpfbdt that holds a texture of that name
  *.dds (loose, in a folder named after its archive: menu/menu_1/Menu08.dds) and PC *.tpf / *.tpf.dcx: textures into the Switch TPF entry of that name
  event/*.emevd.dcx          events: same format on both, used as they are (recompressed)
  sfx/*.ffxbnd.dcx            effects: the ones the mod removes (empty FFX) are emptied in the Switch archive; changed FFX are not converted
  movww/*.bik                movies: re-encoded to the Switch's H.264 mp4 (needs ffmpeg)
  sound/frpg_main.fsb         sounds: PC MP3 samples the mod changes, re-encoded (FADPCM) into the Switch sound/frpg_main.bank (fsb.py, needs ffmpeg)
  map/MapStudio/*.msb         map layouts: the PC map re-laid in the Switch layout (msb.py)
  chr/*.anibnd.dcx           animation events: PC TAE animations the mod changes, into the Switch TAE (tae.py)
  script/talk/*.talkesdbnd.dcx  talk scripts: each PC script re-laid in the Switch ESD layout (esd.py), in the Switch archive
Output: a folder in archive-path layout for the launcher's overlay, and port.tsv (one line per mod file: what happened)."""
import sys, os, re, struct, zlib
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, '..', 'dsr-pc-textures'))
from fsfmt import fs_hash, bhd5_entries, bnd3_parse, bnd3_files, bnd3_rebuild, bhf3_rebuild, tpf_parse, dds_info
from nvntex import read_entry, build_entry, tpf_rebuild
import fmg, esd, tae, msb, fsb, numpy as np

KNOWN = {'chr', 'parts', 'map', 'msg', 'param', 'sfx', 'menu', 'font', 'obj', 'other', 'event', 'facegen', 'mtd', 'paramdef', 'remo', 'script', 'shader', 'sound', 'movww'}
TEX_ARCHIVES = ('.tpf.dcx', '.tpf', '.fgbnd', '.fgbnd.dcx', '.ffxbnd.dcx', '.ffxbnd', '.chrbnd.dcx', '.partsbnd.dcx', '.objbnd.dcx')

class Rom:
    def __init__(self, R):
        self.R = R; self.idx = [bhd5_entries(f'{R}/dvdbnd{i}.bhd5') for i in range(2)]
    def get(self, p):
        h = fs_hash(p)
        for i in range(2):
            if h in self.idx[i]:
                _, sz, o = self.idx[i][h]
                with open(f'{self.R}/dvdbnd{i}.bdt', 'rb') as f: f.seek(o); return f.read(sz)
        return None

def undcx(d):
    if d[:4] != b'DCX\0': return None, d
    i = d.find(b'DCA\0'); return d[:i + 8], zlib.decompressobj().decompress(d[i + 8:])   # mod files often lack the zlib checksum

def redcx(head, data):
    if head is None: return data
    z = zlib.compress(data, 9); h = bytearray(head); struct.pack_into('>II', h, 0x1c, len(data), len(z)); return bytes(h) + z

def leaf(n): return n.replace('/', '\\').split('\\')[-1].lower()

# ---------- text ----------
# A language's text is spread over item.msgbnd and menu.msgbnd, each table keyed by its BND id. The patch tables (ids 100-124: item names and descriptions,
# dialogue, system messages) override the base ones (10-29, 1-92) in game; the Switch build keeps every patch table in menu.msgbnd, the PC one splits them
# across both files. So text is merged by table id into every Switch msgbnd of the language, and a PC change to a base table also goes to its patch table.
PATCH_OF = {10: 111, 11: 115, 12: 117, 13: 113, 14: 118, 18: 119, 19: 120, 20: 110, 21: 114, 22: 116, 23: 112, 24: 100, 25: 106, 26: 108, 27: 109, 29: 105,
            30: 101, 78: 102, 92: 103, 1: 104, 2: 107, 80: 121, 79: 122, 77: 123, 76: 124}

def msg_changes(sw_tables, pc):
    """{table id: {entry id: text}} the PC msgbnd changes compared with the Switch tables"""
    _, p = undcx(pc); ch = {}
    for e, (n, x) in zip(bnd3_parse(p)[1], bnd3_files(p)):
        tid = e.get('id')
        try: t = fmg.parse(x)
        except Exception: continue
        ref = sw_tables.get(tid)
        if ref is None: continue
        d = {i: v for i, v in t.items() if ref.get(i, 0) != v and v is not None}
        if d:
            ch.setdefault(tid, {}).update(d)
            if tid in PATCH_OF and PATCH_OF[tid] in sw_tables: ch.setdefault(PATCH_OF[tid], {}).update({i: v for i, v in d.items() if sw_tables[PATCH_OF[tid]].get(i, 0) != v})
    return ch

def apply_msg(sw, ch):
    head, s = undcx(sw); outs = []; k = 0
    for e, (n, x) in zip(bnd3_parse(s)[1], bnd3_files(s)):
        d = ch.get(e.get('id'))
        if d:
            t = fmg.parse(x); t.update(d); k += len(d); x = fmg.write(t, x[8])
        outs.append(x)
    return (redcx(head, bnd3_rebuild(s, outs)) if k else None), k

def sw_msg_tables(swfiles):
    out = {}
    for sw in swfiles:
        _, s = undcx(sw)
        for e, (n, x) in zip(bnd3_parse(s)[1], bnd3_files(s)): out[e.get('id')] = fmg.parse(x)
    return out

# ---------- params ----------
def param_rows(d):
    n = struct.unpack_from('<H', d, 0xa)[0]
    rows = [struct.unpack_from('<III', d, 0x30 + 12 * i) for i in range(n)]
    offs = sorted({r[1] for r in rows})
    end = min([r[2] for r in rows if r[2]] + [len(d)])
    size = (offs[1] - offs[0]) if len(offs) > 1 else end - offs[0]
    return {r[0]: r[1] for r in rows}, size

def port_param(sw, pc):
    srows, ss = param_rows(sw); prows, ps = param_rows(pc)
    if ss != ps: return None, f'row size {ps} (PC) / {ss} (Switch)'
    out = bytearray(sw); k = 0; extra = 0
    for rid, o in prows.items():
        if rid not in srows: extra += 1; continue
        a = pc[o:o + ps]
        if out[srows[rid]:srows[rid] + ss] != a: out[srows[rid]:srows[rid] + ss] = a; k += 1
    return (bytes(out) if k else None), f'{k} rows' + (f', {extra} rows the Switch file lacks skipped' if extra else '')

def port_parambnd(sw, pc):
    head, s = undcx(sw); _, p = undcx(pc)
    pcs = {leaf(n): x for n, x in bnd3_files(p)}; outs = []; notes = []; changed = 0
    for n, x in bnd3_files(s):
        y = pcs.get(leaf(n))
        if y is not None:
            r, why = port_param(x, y)
            if r is not None: x = r; changed += 1
            if r is not None or 'size' in why: notes.append(f'{leaf(n)}: {why}')
        outs.append(x)
    return (redcx(head, bnd3_rebuild(s, outs)) if changed else None), '; '.join(notes) or 'no change'

# ---------- textures ----------
ETC = None
def encode(nvn, img):
    global ETC
    if ETC is None: import etcpak as ETC
    H, W = img.shape[:2]; ph, pw = -(-H // 4) * 4, -(-W // 4) * 4
    if (ph, pw) != (H, W): q = np.zeros((ph, pw, 4), np.uint8); q[:H, :W] = img; img = q
    f = {0x42: ETC.compress_bc1, 0x44: ETC.compress_bc3, 0x49: ETC.compress_bc4, 0x4b: ETC.compress_bc5, 0x4d: ETC.compress_bc7}[nvn]
    return f(np.ascontiguousarray(img).tobytes(), pw, ph)

DDS_NVN = {'BC1': 0x42, 'BC3': 0x44, 'BC4': 0x49, 'BC5': 0x4b, 'BC7': 0x4d}
def dds_rgba(d, di, lvl):
    """RGBA uint8 of one DDS level (any format texio decodes, plus uncompressed 32-bit with channel masks)"""
    import texio
    w, h = max(1, di['w'] >> lvl), max(1, di['h'] >> lvl)
    if di['fmt'].startswith('RGB'):
        bpp = struct.unpack_from('<I', d, 88)[0] // 8; masks = struct.unpack_from('<4I', d, 92)
        o = di['data_off'] + sum(max(1, di['w'] >> i) * max(1, di['h'] >> i) * bpp for i in range(lvl))
        px = np.frombuffer(d[o:o + w * h * bpp], np.uint8).reshape(h, w, bpp).astype(np.uint32)
        v = sum(px[..., i] << (8 * i) for i in range(bpp)); out = np.empty((h, w, 4), np.uint8)
        for c, m in enumerate(masks):
            if not m: out[..., c] = 255; continue
            sh = (m & -m).bit_length() - 1; out[..., c] = ((v & m) >> sh) * 255 // (m >> sh)
        return out
    bpb = texio.BPB[di['fmt']]; o = di['data_off']
    for i in range(lvl): o += max(1, (max(1, di['w'] >> i) + 3) // 4) * max(1, (max(1, di['h'] >> i) + 3) // 4) * bpb
    n = max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * bpb
    return np.ascontiguousarray(texio.dec_linear(di['fmt'], d[o:o + n], w, h))

def tex_entry(t, e, dds):
    """New Switch TPF entry from a DDS, in the Switch entry's own format (PC blocks copied when the formats match, else re-encoded)"""
    di = dds_info(dds); sw = struct.unpack_from('<64I', t, e['off']); nvn = sw[20]
    if di['cube'] or sw[10] != 2: raise ValueError('not a 2D texture')
    if nvn not in (0x42, 0x44, 0x49, 0x4b, 0x4d): nvn = 0x44
    W, H, mips = di['w'], di['h'], di['mips']
    if DDS_NVN.get(di['fmt']) == nvn and di['dxgi'] not in (72, 99):
        bpb = 8 if nvn in (0x42, 0x49) else 16; o = di['data_off']; lv = []
        for i in range(mips):
            n = max(1, (max(1, W >> i) + 3) // 4) * max(1, (max(1, H >> i) + 3) // 4) * bpb; lv.append(dds[o:o + n]); o += n
    else:
        lv = []
        for i in range(mips):
            img = dds_rgba(dds, di, i)
            if nvn == 0x42 and img[..., 3].min() < 128 and di['fmt'] != 'BC1': nvn = 0x44; return tex_entry_fmt(t, e, dds, di, 0x44)
            lv.append(encode(nvn, img))
    return build_entry(t[e['off']:e['off'] + 0x200], W, H, nvn, lv), nvn

def tex_entry_fmt(t, e, dds, di, nvn):
    lv = [encode(nvn, dds_rgba(dds, di, i)) for i in range(di['mips'])]
    return build_entry(t[e['off']:e['off'] + 0x200], di['w'], di['h'], nvn, lv), nvn

TPF_FMT = {0x42: 0, 0x44: 5, 0x49: 24, 0x4b: 24, 0x4d: 36}
def redo_tpf(t, texs, notes):
    hd, es = tpf_parse(t); repl = {}; fmts = {}
    for e in es:
        dds = texs.get(e['name'].lower())
        if dds is None: continue
        try: blob, nvn = tex_entry(t, e, dds)
        except Exception as ex: notes.append(f'{e["name"]}: not converted ({ex})'); continue
        repl[e['i']] = blob; fmts[e['i']] = nvn; notes.append(f'{e["name"]}: replaced')
    if not repl: return None
    out = bytearray(tpf_rebuild(t, repl))
    for i, nvn in fmts.items():
        if struct.unpack_from('<64I', t, es[i]['off'])[20] != nvn: out[0x10 + 20 * i + 8] = TPF_FMT[nvn]   # the TPF table's format byte follows the new format
    return bytes(out)

def redo(d, texs, notes):
    """d: Switch file (DCX / BND3 / TPF); returns new bytes or None when nothing in it matched"""
    head, raw = undcx(d)
    if raw[:4] == b'TPF\0': new = redo_tpf(raw, texs, notes)
    elif raw[:4] == b'BND3':
        outs = []; n = 0
        for nm, x in bnd3_files(raw):
            r = redo(x, texs, notes); outs.append(r if r is not None else x); n += r is not None
        new = bnd3_rebuild(raw, outs) if n else None
    else: return None
    return None if new is None else redcx(head, new)

def pc_tpf_textures(d):
    _, t = undcx(d)
    if t[:4] == b'BND3':
        out = {}
        for _, x in bnd3_files(t): out.update(pc_tpf_textures(x))
        return out
    if t[:4] != b'TPF\0': return {}
    hd, es = tpf_parse(t)
    return {e['name'].lower(): t[e['off']:e['off'] + e['size']] for e in es} if hd['platform'] == 0 else {}

def unchanged(sw_t, name, dds):
    """True when the PC texture shows what the Switch one shows (a whole-archive PC mod carries every texture, most untouched)"""
    try:
        import texio
        hd, es = tpf_parse(sw_t); e = next(e for e in es if e['name'].lower() == name)
        a = read_entry(sw_t, e); fmt = texio.NVN[a['nvn']][0]; di = dds_info(dds)
        if (di['w'], di['h']) != (a['w'], a['h']): return False
        A = texio.dec_linear(fmt, a['levels'][0], a['w'], a['h']).astype(int); B = dds_rgba(dds, di, 0).astype(int)
        return float(np.abs(A - B).mean()) < 3
    except Exception: return False

# ---------- movies ----------
def bik_to_mp4(path):
    import subprocess, tempfile
    ff = fsb.ffmpeg()
    with tempfile.TemporaryDirectory() as t:
        out = os.path.join(t, 'm.mp4')
        enc = ['-c:v', 'h264_videotoolbox', '-profile:v', 'high', '-b:v', '8M'] if sys.platform == 'darwin' else ['-c:v', 'libx264', '-crf', '18']
        r = subprocess.run([ff, '-v', 'error', '-y', '-i', path, '-an', *enc, '-pix_fmt', 'yuv420p', '-r', '30000/1001', '-movflags', '+faststart', out], capture_output=True)
        if r.returncode: raise ValueError('ffmpeg: ' + r.stderr.decode()[-150:])
        return open(out, 'rb').read()

# ---------- driver ----------
def mod_files(root):
    """(path inside the game data, lowercase with '/', file path) for every file under a known top folder, at any depth of wrapper folders"""
    out = []
    for dp, _, fs in os.walk(root):
        for f in fs:
            full = os.path.join(dp, f); parts = os.path.relpath(full, root).split(os.sep)
            k = next((i for i, p in enumerate(parts) if p.lower() in KNOWN), None)
            if k is not None: out.append(('/'.join(parts[k:]), full))
            elif re.fullmatch(r'c\d{4}\.(anibnd|chrbnd)\.dcx', f.lower()): out.append(('chr/' + f, full))
            elif f.lower() == 'frpg_main.fsb': out.append(('sound/frpg_main.fsb', full))   # PC sound bank (DS3 Sound Mod ships it bare, next to its .bak)   # loose character file (Modern Roll ships c0000.anibnd.dcx bare)
    return out

def main(mod, R, out):
    rom = Rom(R); rep = []; written = {}
    def put(path, data):
        written[path] = data
    def sw(path):
        if path in written: return written[path]
        return rom.get('/' + path)
    loose = {}   # archive path -> {texture name: dds}
    maptex = {}  # map/mXX -> {texture name: dds}: PC and Switch spread a map's textures over mXX_0000..3 differently, so each goes where the Switch has it
    for rel, full in sorted(mod_files(mod)):
        low = rel.lower(); d = open(full, 'rb').read()
        try:
            if low.endswith('.dds') and re.fullmatch(r'map/m\d\d/m\d\d_\d{4}', rel.rsplit('/', 1)[0].lower()):   # map texture (TPUP layout map/m10/m10_0001/x.dds)
                maptex.setdefault(rel.rsplit('/', 2)[0], {})[rel.rsplit('/', 1)[1][:-4].lower()] = d; continue
            if low.endswith('.dds'):
                folder, name = rel.rsplit('/', 1)
                arc = next((folder + s for s in TEX_ARCHIVES if rom.get('/' + folder + s) is not None), None)
                if arc is None: rep.append((rel, 'skipped', f'no Switch archive {folder}.*')); continue
                loose.setdefault(arc, {})[name[:-4].lower()] = d; continue
            if low.startswith(('movww/', 'movjp/')) and low.endswith('.bik'):   # PC Bink movie -> the Switch H.264 mp4 of the same name (no audio track, like the Switch's)
                mp4 = rel[:-4] + '.mp4'
                if rom.get('/' + mp4) is None and not os.path.exists(os.path.join(R, mp4)): rep.append((rel, 'skipped', 'the Switch game has no such movie')); continue
                put(mp4, bik_to_mp4(full)); rep.append((rel, 'ported', f'movie re-encoded to {mp4} (H.264, no sound)')); continue
            if low == 'sound/frpg_main.fsb':   # PC FSB4 (MP3) bank -> the Switch FMOD Studio bank (FSB5, FADPCM); the .bak beside it, when shipped, is the PC original
                bak = full + '.bak'; base = open(bak, 'rb').read() if os.path.exists(bak) else None
                new, names = fsb.port_fsb4(d, rom.get('/sound/frpg_main.bank'), base)
                if new is None: rep.append((rel, 'unchanged', 'no sound differs')); continue
                put('sound/frpg_main.bank', new); rep.append((rel, 'ported', f'{len(names)} sounds re-encoded into sound/frpg_main.bank')); continue
            s = sw(rel)
            if s is None: rep.append((rel, 'skipped', 'the Switch game has no such file')); continue
            if low.endswith('.msgbnd.dcx'):
                lang = rel.rsplit('/', 1)[0]; paths = [f'{lang}/item.msgbnd.dcx', f'{lang}/menu.msgbnd.dcx']
                ch = msg_changes(sw_msg_tables([sw(q) for q in paths if sw(q)]), d); parts = []
                for q in paths:
                    if sw(q) is None: continue
                    r, k = apply_msg(sw(q), ch)
                    if r is not None: put(q, r); parts.append(f'{q.rsplit("/", 1)[1]} {k}')
                rep.append((rel, 'ported' if parts else 'unchanged', 'text entries: ' + (', '.join(parts) or 'none differ'))); continue
            elif low.endswith('.parambnd.dcx'): new, why = port_parambnd(s, d)
            elif low.endswith(('.tpf', '.tpf.dcx')):
                texs = pc_tpf_textures(d); _, st = undcx(s)
                texs = {k: v for k, v in texs.items() if not unchanged(st, k, v)} if st[:4] == b'TPF\0' else texs
                notes = []; new = redo(s, texs, notes) if texs else None; why = f'{len(texs)} changed textures: ' + ', '.join(notes) if texs else 'no texture differs from the Switch one'
            elif low.endswith('.emevd.dcx') or low.endswith('.emevd'):
                h, e = undcx(d); hs, _ = undcx(s)
                if e[:4] != b'EVD\0': raise ValueError('not an EMEVD')
                new, why = redcx(hs, e), 'event script used as is'
            elif low.endswith('.anibnd.dcx'):   # animation events: PC TAE (32-bit) onto the Switch TAE (64-bit) of the same name; skeleton and Havok files stay Switch
                _, p = undcx(d); hs, t = undcx(s)
                pcs = {leaf(n): x for n, x in bnd3_files(p) if n.lower().endswith('.tae')}; files = []; n_anim = 0; n_file = 0
                for n, x in bnd3_files(t):
                    if leaf(n) in pcs:
                        y, taken = tae.port(pcs[leaf(n)], x)
                        if taken: files.append(y); n_anim += len(taken); n_file += 1; continue
                    files.append(x)
                new = redcx(hs, bnd3_rebuild(t, files)) if n_anim else None
                why = f'{n_anim} animations from the mod in {n_file} TAE files' if n_anim else 'no animation differs from the Switch one'
            elif low.endswith('.msb'):   # map layout: the mod's whole PC map re-laid in the Switch layout (64-bit offsets, wider data blocks), so its own indices stay consistent
                if d[:4] != b'\0\0\0\0' or s[:4] != b'\0\0\0\0': raise ValueError('not an uncompressed MSB')
                new = msb.write(msb.to_switch(msb.parse(d, 4)), 8)
                why = 'map layout: the PC map re-laid in the Switch layout (Switch-only position fixes in this map are not kept)'
            elif low.endswith('.ffxbnd.dcx'):   # effects: PC FFX files are another layout; a mod that removes an effect ships it empty, and that the Switch archive can take
                _, p = undcx(d); hs, t = undcx(s)
                empty = {leaf(n) for n, x in bnd3_files(p) if n.lower().endswith('.ffx') and len(x) == 0}
                if not empty: rep.append((rel, 'skipped', 'effect files (FFX) are not converted, only removed ones')); continue
                new = redcx(hs, bnd3_rebuild(t, [b'' if leaf(n) in empty else x for n, x in bnd3_files(t)]))
                why = f'{len(empty)} effects removed: ' + ', '.join(sorted(empty)) + '; changed effects (other FFX) are not converted'
            elif low.endswith('.talkesdbnd.dcx'):   # the Switch talk engine reads a later ESD layout (hash, -1 for empty lists, terminated name): each PC script is re-laid
                _, p = undcx(d); hs, t = undcx(s)
                pcs = {leaf(n): esd.write(esd.parse(x)) for n, x in bnd3_files(p)}; names = [leaf(n) for n, _ in bnd3_files(t)]
                miss = [n for n in pcs if n not in names]
                new = redcx(hs, bnd3_rebuild(t, [pcs.get(leaf(n), x) for n, x in bnd3_files(t)]))
                why = f'{sum(n in pcs for n in names)} of {len(names)} talk scripts' + (f', {len(miss)} PC-only scripts dropped' if miss else '')
            else: rep.append((rel, 'skipped', 'this file type is not converted yet')); continue
            if new is None: rep.append((rel, 'unchanged', why)); continue
            put(rel, new); rep.append((rel, 'ported', why))
        except Exception as ex: rep.append((rel, 'failed', repr(ex)[:200]))
    for arc, texs in loose.items():
        notes = []
        try:
            new = redo(sw(arc), texs, notes)
            if new is not None: put(arc, new)
            found = {n.split(':')[0].lower() for n in notes}
            for n in texs:
                if n not in found: notes.append(f'{n}: no such texture in {arc}')
            rep.append((arc, 'ported' if new is not None else 'failed', '; '.join(notes)))
        except Exception as ex: rep.append((arc, 'failed', repr(ex)[:200]))
    for mdir, texs in maptex.items():
        left = dict(texs); area = mdir.rsplit('/', 1)[1]
        for k in range(10):
            bhd_p = f'{mdir}/{area}_{k:04d}.tpfbhd'; bhd = rom.get('/' + bhd_p)
            if bhd is None: continue
            bdt = rom.get('/' + bhd_p[:-3] + 'bdt'); files = bnd3_files(bhd, bdt); outs = []; notes = []
            for nm, x in files:
                tn = re.sub(r'\.tpf(\.dcx)?$', '', leaf(nm)) if re.search(r'\.tpf(\.dcx)?$', leaf(nm)) else None
                hit = {t: left[t] for t in left if tn and t == tn.lower()}
                r = redo(x, hit, notes) if hit else None
                outs.append(r if r is not None else x)
                if r is not None: left.pop(tn.lower(), None)
            if any(o is not x for o, (_, x) in zip(outs, files)):
                h2, b2 = bhf3_rebuild(bhd, bdt, outs); put(bhd_p, h2); put(bhd_p[:-3] + 'bdt', b2)
                rep.append((bhd_p, 'ported', f'{sum(o is not x for o, (_, x) in zip(outs, files))} map textures: ' + '; '.join(notes)[:300]))
        for t in left: rep.append((f'{mdir}/{t}.dds', 'skipped', 'no Switch map texture of that name'))
    for path, data in written.items():
        dst = os.path.join(out, path); os.makedirs(os.path.dirname(dst), exist_ok=True); open(dst, 'wb').write(data)
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, 'port.tsv'), 'w') as f:
        for r in rep: f.write('\t'.join(r) + '\n')
    return rep

if __name__ == '__main__':
    if len(sys.argv) != 4: sys.exit(__doc__)
    for r in main(*sys.argv[1:]): print('\t'.join(r))
