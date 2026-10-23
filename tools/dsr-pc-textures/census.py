"""Census: every Switch texture vs its PC counterpart. usage: census.py <RomFS> <PC game dir> <out.tsv> <pc file list>"""
import sys, os, struct, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fsfmt import *
from multiprocessing import Pool
import os as _os
R = _os.environ.get('DSR_ROMFS', '')   # Switch RomFS (dvdbnd0/1); set by the command line or the importer
P = _os.environ.get('DSR_PC', '')      # PC game folder
ES = {}
def load_index():
    ES.clear()
    if not R: return
    for a in (0, 1):
        for h, v in bhd5_entries(f'{R}/dvdbnd{a}.bhd5').items(): ES[h] = (a, v)
load_index()

def sw_read(p):
    h = fs_hash(p)
    if h not in ES: return None
    a, (_, sz, o) = ES[h]
    with open(f'{R}/dvdbnd{a}.bdt', 'rb') as f: f.seek(o); return f.read(sz)

def pc_read(p):
    try: return open(P + p, 'rb').read()
    except FileNotFoundError: return None

def bdt_for(reader, top):
    def g(path):
        # chrbnd -> c####.chrtpfbdt next to it; map xxx.tpfbhd -> xxx.tpfbdt
        if top.endswith('.chrbnd.dcx'): return reader(top.replace('.chrbnd.dcx', '.chrtpfbdt'))
        if top.endswith('.tpfbhd'): return reader(top[:-3] + 'bdt')
        return None
    return g

def texs(reader, top):
    d = reader(top); out = {}
    if d is None: return out
    for inner, t in walk(d, bdt_for(reader, top)):
        try: hd, es = tpf_parse(t)
        except Exception: continue
        for e in es: out.setdefault(e['name'], (inner, hd, e, t))
    return out

def one(top):
    rows = []
    try:
        sw = texs(sw_read, top); pc = texs(pc_read, top)
    except Exception as ex:
        return [(top, '-', 'ERR', repr(ex)[:80], '', '')]
    for n, (inner, hd, e, t) in sw.items():
        if hd['platform'] != 4: rows.append((top, n, f'plat{hd["platform"]}', '', '', 'sw-not-switch')); continue
        h = nvn_hdr(t, e); s = f'{h["w"]}x{h["h"]} nvn{h["nvn"]:#x} m{h["mips"]} t{h["target"]} f{e["fmt"]}'
        if n not in pc: rows.append((top, n, s, '', '', 'pc-missing')); continue
        _, _, pe, pt = pc[n]; di = dds_info(pt[pe['off']:pe['off'] + pe['size']])
        p = f'{di["w"]}x{di["h"]} {di["fmt"]} m{di["mips"]}{" cube" if di["cube"] else ""} f{pe["fmt"]}'
        v = 'larger' if di['w'] * di['h'] > h['w'] * h['h'] else 'smaller' if di['w'] * di['h'] < h['w'] * h['h'] else 'same-size'
        rows.append((top, n, s, p, inner + ' || ' + pc[n][0], v))
    for n in pc:
        if n not in sw: rows.append((top, n, '', 'pc-only', '', 'sw-missing'))
    return rows

if __name__ == '__main__':
    R, P, OUT = sys.argv[1:4]; os.environ['DSR_ROMFS'], os.environ['DSR_PC'] = R, P; load_index()   # spawned workers read the env
    pcl = [l.strip() for l in open(sys.argv[4])]
    tops = [p for p in pcl if fs_hash(p) in ES and (p.endswith(('.chrbnd.dcx', '.tpfbhd', '.objbnd.dcx', '.partsbnd.dcx', '.ffxbnd.dcx', '.tpf.dcx', '.tpf', '.remobnd.dcx')))]
    print(len(tops), 'archives', flush=True)
    with Pool(8) as pool, open(OUT, 'w') as f:
        f.write('archive\ttexture\tswitch\tpc\tinner\tverdict\n'); c = collections.Counter(); k = 0
        for rows in pool.imap_unordered(one, tops, chunksize=4):
            k += 1
            for r in rows: f.write('\t'.join(map(str, r)) + '\n'); c[r[5]] += 1
            if k % 200 == 0: print(k, dict(c), flush=True)
    print(dict(c))
