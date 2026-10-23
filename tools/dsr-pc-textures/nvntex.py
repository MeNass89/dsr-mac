"""Switch TPF texture entries (NVN header + Tegra block-linear data) <-> linear BC block levels."""
import struct, numpy as np

BPB = {0x42: 8, 0x43: 16, 0x44: 16, 0x49: 8, 0x4b: 16, 0x4d: 16}
TAIL = bytes.fromhex('4842764e2400000018000000000000002400000000000000050000000200000000000000000000000000000001000000010000000000000000000000')

def pick_tile(gobs): return 4 if gobs >= 16 else 3 if gobs >= 8 else 2 if gobs >= 4 else 1 if gobs >= 2 else 0
def adj_tile(shift, unit, dim):
    if not shift: return 0
    x = unit << (shift - 1)
    if x >= dim:
        while True:
            shift -= 1
            if not shift: break
            x >>= 1
            if x < dim: break
    return shift

def levels_geom(W, H, mips, bpb, tile=None):
    """[(bw, bh, th, offset, size)] per level, total size, level-0 tile (log2 GOBs)"""
    bh0 = (H + 3) // 4
    if tile is None: tile = pick_tile((bh0 + bh0 // 2 + 7) // 8)
    out = []; off = 0
    for i in range(mips):
        w = max(1, W >> i); h = max(1, H >> i); bw, bh = (w + 3) // 4, (h + 3) // 4
        th = adj_tile(tile, 8, bh); wg = (bw * bpb + 63) // 64; hg = (bh + 7) // 8; ht = (hg + (1 << th) - 1) >> th
        sz = wg * ht << (9 + th); out.append((bw, bh, th, off, sz)); off += sz
    return out, off, tile

_cache = {}
def bl_offsets(bw, bh, bpb, th):
    k = (bw, bh, bpb, th)
    if k in _cache: return _cache[k]
    gbh = 1 << th; gobs_x = (bw * bpb + 63) // 64
    ys, xs = np.mgrid[0:bh, 0:bw]; xb = xs * bpb; xi = xb % 64; yi = ys % 8
    base = (((ys // (8 * gbh)) * gobs_x + xb // 64) * gbh + (ys % (8 * gbh)) // 8) * 512
    off = (base + (xi // 32) * 256 + (yi // 2) * 64 + ((xi % 32) // 16) * 32 + (yi % 2) * 16 + (xi % 16)).astype(np.int64)
    off = (off[..., None] + np.arange(bpb)).reshape(-1)
    if len(_cache) > 64: _cache.clear()
    _cache[k] = off; return off

def unswizzle_level(raw, base, bw, bh, bpb, th):
    return np.frombuffer(raw, np.uint8)[base + bl_offsets(bw, bh, bpb, th)].tobytes()

def swizzle_level(buf, base, lin, bw, bh, bpb, th):
    buf[base + bl_offsets(bw, bh, bpb, th)] = np.frombuffer(lin, np.uint8)

def read_entry(t, e):
    """-> dict(w,h,nvn,mips,levels=[linear bytes per level])"""
    w = struct.unpack_from('<64I', t, e['off']); W, H, nvn, mips, tile = w[16], w[17], w[20], w[21], w[40]
    bpb = BPB[nvn]; geo, total, _ = levels_geom(W, H, mips, bpb, tile)
    raw = t[e['off'] + 0x200: e['off'] + 0x200 + w[13]]
    return dict(w=W, h=H, nvn=nvn, mips=mips, tile=tile, levels=[unswizzle_level(raw, o, bw, bh, bpb, th) for bw, bh, th, o, sz in geo])

def build_entry(proto, W, H, nvn, levels):
    """Switch TPF entry bytes: proto = an existing entry's 0x200 header (fields reused), levels = linear BC blocks per mip"""
    bpb = BPB[nvn]; mips = len(levels); geo, total, tile = levels_geom(W, H, mips, bpb)
    buf = np.zeros(total, np.uint8)
    for (bw, bh, th, o, sz), lin in zip(geo, levels):
        assert len(lin) == bw * bh * bpb, (len(lin), bw, bh); swizzle_level(buf, o, lin, bw, bh, bpb, th)
    w = list(struct.unpack_from('<128I', proto, 0))
    w[13] = w[22] = w[45] = total; w[16], w[17], w[20], w[21], w[40] = W, H, nvn, mips, geo[0][2]   # word 40 = level-0 block height after adjustment
    for i in range(16): w[24 + i] = geo[i + 1][3] if i + 1 < mips else 0   # offsets of levels 1..n (level 0 at 0)
    return struct.pack('<128I', *w) + buf.tobytes() + TAIL

def tpf_rebuild(t, repl):
    """t: Switch TPF bytes; repl: {index: new entry bytes}. Entries are laid out back to back from the first data offset."""
    n = struct.unpack_from('<I', t, 8)[0]; ents = [struct.unpack_from('<II', t, 0x10 + 20 * i) for i in range(n)]
    start = min(o for o, s in ents); head = bytearray(t[:start]); data = bytearray(); pos = start
    order = sorted(range(n), key=lambda i: ents[i][0])
    for i in order:
        o, s = ents[i]; blob = repl.get(i, t[o:o + s])
        struct.pack_into('<II', head, 0x10 + 20 * i, start + len(data), len(blob)); data += blob
    struct.pack_into('<I', head, 4, len(data)); return bytes(head + data)
