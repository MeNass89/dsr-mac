"""Build the "PC textures" mod: Switch archives with each texture replaced by the PC one where the PC one is better.
usage: python -I convert.py <RomFS> <PC game dir> <mod out dir> [--only chr,map,...] [--archives a,b] [--workers 8]
Output: a mod folder in archive-path layout (chr/c2260.chrbnd.dcx, map/m10/m10_0000.tpfbhd + .tpfbdt ...), plus report.tsv.
PC blocks are copied verbatim (BC1/BC3/BC5/BC7, no re-encode) into the Switch NVN layout (Tegra block linear, NVN header, same TPF entry)."""
import sys, os, struct, argparse, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fsfmt import *
from nvntex import read_entry, build_entry, tpf_rebuild, BPB
import texio
from multiprocessing import Pool

PC_NVN = {'BC1': 0x42, 'BC3': 0x44, 'BC5': 0x4b, 'BC7': 0x4d}
RANK = {0x42: 0, 0x43: 1, 0x44: 1, 0x4b: 2, 0x4d: 2}
NO_UPSCALE = os.environ.get('DSR_PCTEX_NO_UPSCALE') == '1'
NORMALS = os.environ.get('DSR_PCTEX_NORMALS', 'bc7')   # PC normals are BC5 (blue reads 0); the Switch shaders expect BC1 normals with blue = 1:
                                                       # skip = keep Switch normals, bc1 / bc7 = transcode with blue forced to 255
import etcpak

def encode(fmt, img):   # RGBA uint8 -> linear BC blocks (padded to 4x4)
    H, W = img.shape[:2]; ph, pw = -(-H // 4) * 4, -(-W // 4) * 4
    if (ph, pw) != (H, W): p = np.zeros((ph, pw, 4), np.uint8); p[:H, :W] = img; p[H:, :W] = img[-1:]; p[:, W:] = p[:, W - 1:W]; img = p
    b = np.ascontiguousarray(img).tobytes()   # etcpak takes RGBA
    return {'BC1': etcpak.compress_bc1, 'BC7': etcpak.compress_bc7}[fmt](b, pw, ph)

def normals_blue(di, lv, fmt):
    out = []
    for i, l in enumerate(lv):
        w, h = max(1, di['w'] >> i), max(1, di['h'] >> i)
        img = texio.dec_linear(di['fmt'], l, w, h).copy(); img[..., 2] = 255; img[..., 3] = 255
        out.append(encode(fmt, img))
    return out
SPEC = os.environ.get('DSR_PCTEX_SPEC', 'skip')   # skip, only (speculars alone, for tests), or fit: PC specular maps remapped to the Switch layout (see spec_fit), larger ones only
SKIP_SUFFIX = ('_s',)    # specular: PC packs other channels (R inverted, G/B different maps), the Switch shader expects grey

def dds_levels(d):
    di = dds_info(d); fmt = di['fmt']; bpb = texio.BPB[fmt]; o = di['data_off']; lv = []
    for i in range(di['mips']):
        w, h = max(1, di['w'] >> i), max(1, di['h'] >> i); n = ((w + 3) // 4) * ((h + 3) // 4) * bpb
        lv.append(d[o:o + n]); o += n
    return di, lv

def lvl_img(fmt, lin, w, h): return texio.dec_linear(fmt, lin, w, h).astype(np.float32)

def common_mip(sw, di, cap=128):
    k = 0
    while (sw['w'] >> k) > cap and k + 1 < sw['mips']: k += 1
    w, h = max(1, sw['w'] >> k), max(1, sw['h'] >> k)
    j = next((j for j in range(di['mips']) if max(1, di['w'] >> j) == w and max(1, di['h'] >> j) == h), None)
    return k, j, w, h

def spec_fit(sw, di, lv):
    """PC _s maps pack other channels (R = inverted gloss-like, G/B other maps); the Switch _s is a grey or colour specular. The relation differs
    per material, so each Switch channel is fitted as a linear function of the PC RGB on a common small mip, then applied to every PC level.
    Accepted only when the fit explains the Switch map well (mean error < 6 and R^2 > 0.8 on each channel with variation)."""
    k, j, w, h = common_mip(sw, di)
    if j is None: return None, 'no-common-mip'
    a = texio.dec_linear(texio.NVN[sw['nvn']][0], sw['levels'][k], w, h).reshape(-1, 4).astype(np.float64)
    b = texio.dec_linear(di['fmt'], lv[j], w, h).reshape(-1, 4).astype(np.float64)
    A = np.c_[b[:, :3], np.ones(len(b))]; coef = []; worst = 0.0
    for ch in range(3):
        cf = np.linalg.lstsq(A, a[:, ch], rcond=None)[0]; p = A @ cf; err = np.abs(p - a[:, ch]).mean(); var = a[:, ch].std()
        r2 = 1 - ((p - a[:, ch]) ** 2).mean() / max(var ** 2, 1e-6)
        if err > 6 or (var > 4 and r2 < 0.8): return None, f'spec-fit-poor ch{ch} err={err:.1f} r2={r2:.2f}'
        coef.append(cf); worst = max(worst, err)
    out = []
    for i, l in enumerate(lv):
        lw, lh = max(1, di['w'] >> i), max(1, di['h'] >> i)
        img = texio.dec_linear(di['fmt'], l, lw, lh).astype(np.float64); Ai = np.c_[img[..., :3].reshape(-1, 3), np.ones(lw * lh)]
        o = np.empty((lh, lw, 4), np.uint8); o[..., 3] = 255
        for ch in range(3): o[..., ch] = np.clip(Ai @ coef[ch], 0, 255).reshape(lh, lw)
        out.append(encode('BC1', o))
    return out, f'spec-fit err={worst:.1f}'

def similar(sw, swfmt, di, pclv, normal):
    """compare at a common mip <=128 px: PC content must be the Switch content"""
    k = 0
    while (sw['w'] >> k) > (512 if normal else 128) and k + 1 < sw['mips']: k += 1
    w, h = max(1, sw['w'] >> k), max(1, sw['h'] >> k)
    j = next((j for j in range(di['mips']) if max(1, di['w'] >> j) == w and max(1, di['h'] >> j) == h), None)
    if j is None: return False, 'no-common-mip'
    a = lvl_img(swfmt, sw['levels'][k], w, h).reshape(-1, 4); b = lvl_img(di['fmt'], pclv[j], w, h).reshape(-1, 4)
    ch = (0, 1) if normal else (0, 1, 2)
    if not normal:   # alpha coverage must match (alpha test / blend): fraction of pixels whose alpha side flips
        flip = float(((a[:, 3] < 128) != (b[:, 3] < 128)).mean())
        if flip > 0.02: return False, f'alpha-differs {flip:.2f}'
    cs = []
    for c in ch:
        if a[:, c].std() < 2 and b[:, c].std() < 2: cs.append(1.0 if abs(a[:, c].mean() - b[:, c].mean()) < 12 else 0.0); continue
        if a[:, c].std() < 2 or b[:, c].std() < 2: cs.append(0.0); continue
        cs.append(float(np.corrcoef(a[:, c], b[:, c])[0, 1]))
    mad = float(np.abs(a[:, list(ch)] - b[:, list(ch)]).mean())
    ok = (min(cs) > 0.6 and mad < 12) if normal else (min(cs) > 0.80 and mad < 24)
    return ok, f'corr={min(cs):.2f} mad={mad:.1f}'

def decide(t, e, pcd, name):
    """-> (new entry bytes or None, report string)"""
    spec = name.lower().endswith(SKIP_SUFFIX)
    if spec and SPEC == 'skip': return None, 'skip-specular'
    if not spec and SPEC == 'only': return None, 'skip-not-specular'
    w = struct.unpack_from('<64I', t, e['off'])
    if w[10] != 2 or w[18] != 1 or w[19] != 1: return None, 'skip-not-2d'
    if w[20] not in BPB or w[20] in (0x49,): return None, f'skip-sw-fmt{w[20]:#x}'
    di, lv = dds_levels(pcd)
    if di['fmt'] not in PC_NVN or di['cube'] or di['dxgi'] in (72, 99): return None, f'skip-pc-{di["fmt"]}{di["dxgi"] or ""}'
    sw = read_entry(t, e); nvn = PC_NVN[di['fmt']]
    normal = name.lower().endswith('_n') and di['fmt'] == 'BC5'
    if normal and NORMALS == 'skip': return None, 'skip-normal'
    if normal: nvn = {'bc1': 0x42, 'bc7': 0x4d}[NORMALS]
    if di['w'] * sw['h'] != di['h'] * sw['w']: return None, 'skip-aspect'
    larger = di['w'] > sw['w'] and not NO_UPSCALE; better_fmt = RANK.get(nvn, 0) > RANK.get(sw['nvn'], 0)
    if normal and NORMALS == 'bc1': better_fmt = False   # BC5 -> BC1 transcode: only worth it for more pixels
    if spec:   # specular: only more pixels is a gain; the output stays BC1 like the Switch one
        if not larger or sw['nvn'] != 0x42: return None, 'no-gain'
        lv2, why = spec_fit(sw, di, lv)
        if lv2 is None: return None, 'different-content ' + why
        mips = min(di['mips'], sw['mips'] + (di['w'].bit_length() - sw['w'].bit_length()))
        return build_entry(t[e['off']:e['off'] + 0x200], di['w'], di['h'], 0x42, lv2[:mips]), f'replaced {sw["w"]}x{sw["h"]} BC1 -> {di["w"]}x{di["h"]} BC1 {why}'
    if not (larger or better_fmt): return None, 'no-gain'
    if di['w'] < sw['w']: return None, 'pc-smaller'
    if di['w'] > sw['w'] and NO_UPSCALE:   # quality-only set: PC blocks from the mip that has the Switch size
        k = di['w'].bit_length() - sw['w'].bit_length(); di = dict(di, w=sw['w'], h=sw['h'], mips=di['mips'] - k); lv = lv[k:]
    swfmt = texio.NVN[sw['nvn']][0]
    ok, why = similar(sw, swfmt, di, lv, name.lower().endswith('_n'))
    if not ok: return None, 'different-content ' + why
    # mips: PC chain, but never fewer levels below the Switch smallest size than the Switch had
    mips = min(di['mips'], sw['mips'] + (di['w'].bit_length() - sw['w'].bit_length()))
    lv = lv[:mips]
    if normal: lv = normals_blue(dict(di, mips=mips), lv, 'BC1' if nvn == 0x42 else 'BC7')
    blob = build_entry(t[e['off']:e['off'] + 0x200], di['w'], di['h'], nvn, lv)
    return blob, f'replaced {sw["w"]}x{sw["h"]} {swfmt} -> {di["w"]}x{di["h"]} {di["fmt"]} {why}'

def pc_textures(P, top):
    out = {}
    def rd(p):
        try: return open(P + p, 'rb').read()
        except FileNotFoundError: return None
    d = rd(top)
    if d is None: return out
    def getbdt(path):
        if top.endswith('.chrbnd.dcx'): return rd(top.replace('.chrbnd.dcx', '.chrtpfbdt'))
        if top.endswith('.tpfbhd'): return rd(top[:-3] + 'bdt')
    srcs = [(top, d)]
    if top.endswith('.tpfbhd'):   # PC and Switch split a map's textures differently over mXX_0000..3: search the whole folder, own file first
        dirp = os.path.dirname(top)
        for f in sorted(os.listdir(P + dirp)):
            if f.endswith('.tpfbhd') and dirp + '/' + f != top: srcs.append((dirp + '/' + f, rd(dirp + '/' + f)))
    for src, dd in srcs:
        if dd is None: continue
        gb = (lambda path, s=src: rd(s[:-3] + 'bdt')) if src.endswith('.tpfbhd') else getbdt
        for inner, t in walk(dd, gb):
            try: hd, es = tpf_parse(t)
            except Exception: continue
            for e in es: out.setdefault(e['name'], t[e['off']:e['off'] + e['size']])
    return out

def redo_tpf(t, pcs, rep, where):
    hd, es = tpf_parse(t)
    if hd['platform'] != 4: return t, 0
    repl = {}
    for e in es:
        if e['name'] not in pcs: rep.append((where, e['name'], 'pc-missing')); continue
        try: blob, why = decide(t, e, pcs[e['name']], e['name'])
        except Exception as ex: blob, why = None, 'error ' + repr(ex)[:60]
        rep.append((where, e['name'], why))
        if blob is not None: repl[e['i']] = blob
    return (tpf_rebuild(t, repl), len(repl)) if repl else (t, 0)

def redo(d, pcs, rep, where, getbdt):
    """returns (new data or None if unchanged, extra outputs {suffix: bytes})"""
    dcx = is_dcx(d); head, raw = undcx(d) if dcx else (None, d); m = raw[:4]; n = 0; extra = {}
    if m == b'TPF\0': new, n = redo_tpf(raw, pcs, rep, where)
    elif m == b'BND3':
        outs = []
        for (nm, x) in bnd3_files(raw):
            r, ex = redo(x, pcs, rep, where + '|' + nm.split('\\')[-1], getbdt)
            outs.append(r if r is not None else x); n += r is not None; extra.update(ex)
        new = bnd3_rebuild(raw, outs) if n else raw
    elif m == b'BHF3':
        bdt = getbdt(); outs = []
        for (nm, x) in bnd3_files(raw, bdt):
            r, _ = redo(x, pcs, rep, where + '|' + nm.split('\\')[-1], None)
            outs.append(r if r is not None else x); n += r is not None
        if n: raw2, bdt2 = bhf3_rebuild(raw, bdt, outs); extra['bdt'] = bdt2; new = raw2
        else: new = raw
    else: return None, {}
    if not n: return None, {}
    return (redcx(head, new) if dcx else new), extra

def one(job):
    R, P, out, top = job
    import census; census.R = R; census.load_index()
    rep = []
    try:
        d = census.sw_read(top); pcs = pc_textures(P, top)
        if d is None: return [(top, '-', 'switch-missing')]
        bdtp = top[:-3] + 'bdt' if top.endswith('.tpfbhd') else top.replace('.chrbnd.dcx', '.chrtpfbdt') if top.endswith('.chrbnd.dcx') else None
        new, extra = redo(d, pcs, rep, top, (lambda: census.sw_read(bdtp)) if bdtp else None)
        if new is not None:
            dst = out + top; os.makedirs(os.path.dirname(dst), exist_ok=True)
            open(dst, 'wb').write(new)
            if 'bdt' in extra: open(out + bdtp, 'wb').write(extra['bdt'])
    except Exception as ex:
        rep.append((top, '-', 'archive-error ' + repr(ex)[:100]))
    return rep

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('romfs'); ap.add_argument('pc'); ap.add_argument('out')
    ap.add_argument('--only', default='chr,map,obj,parts,sfx'); ap.add_argument('--archives', default=''); ap.add_argument('--workers', type=int, default=6)
    a = ap.parse_args()
    os.environ['DSR_ROMFS'] = a.romfs
    import census
    census.R = a.romfs; census.load_index()
    if a.archives: tops = a.archives.split(',')
    else:
        tops = []
        for root, _, fs in os.walk(a.pc):
            for f in fs:
                p = '/' + os.path.relpath(os.path.join(root, f), a.pc).replace(os.sep, '/')
                if p.split('/')[1] in a.only.split(',') and p.endswith(('.chrbnd.dcx', '.tpfbhd', '.objbnd.dcx', '.partsbnd.dcx', '.ffxbnd.dcx', '.tpf.dcx', '.tpf')) \
                   and fs_hash(p) in census.ES: tops.append(p)
    tops.sort(key=lambda p: -os.path.getsize(a.pc + p) if os.path.exists(a.pc + p) else 0)
    print(len(tops), 'archives', flush=True); os.makedirs(a.out, exist_ok=True)
    import collections; c = collections.Counter(); k = 0
    with Pool(a.workers) as pool, open(os.path.join(a.out, '..', os.path.basename(a.out.rstrip('/')) + '.report.tsv'), 'w') as f:
        for rep in pool.imap_unordered(one, [(a.romfs, a.pc, a.out, t) for t in tops]):
            k += 1
            for r in rep: f.write('\t'.join(r) + '\n'); c[r[2].split()[0]] += 1
            if k % 100 == 0: print(k, dict(c), flush=True)
    print(dict(c))
