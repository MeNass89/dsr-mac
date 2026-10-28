# DS1 long-format ESD (fsSL, talk scripts): parse to index form and write in the Switch build's layout (16-byte hash at 0x70, -1 offset for every empty list,
# name UTF-16 with its terminator at an even offset). Records keep their order and sharing. write(parse(x), hash) gives back every Switch script byte for byte.
import struct, hashlib
D = 0x6c
def parse(d):
    h = list(struct.unpack_from('<27i', d, 0)); q = lambda o: struct.unpack_from('<q', d, D + o)[0]
    gc = h[10]; go = q(0x18); groups = [struct.unpack_from('<4q', d, D + go + 32 * g) for g in range(gc)]
    so = groups[0][1] if gc else 72 + 32 * gc
    co = so + 72 * h[12]; mo = co + 56 * h[14]; ao = mo + 24 * h[16]; xo = h[19]
    S = lambda off, base, size: -1 if off == -1 else (off - base) // size
    blob = lambda o, n: bytes(d[D + o:D + o + n]) if n else None
    states = []
    for s in range(h[12]):
        r = struct.unpack_from('<9q', d, D + so + 72 * s)
        states.append((r[0], S(r[1], xo, 8) if r[2] else -1, r[2], S(r[3], mo, 24) if r[4] else -1, r[4], S(r[5], mo, 24) if r[6] else -1, r[6], S(r[7], mo, 24) if r[8] else -1, r[8]))
    conds = []
    for c in range(h[14]):
        r = struct.unpack_from('<7q', d, D + co + 56 * c)
        conds.append((S(r[0], so, 72), S(r[1], mo, 24) if r[2] else -1, r[2], S(r[3], xo, 8) if r[4] else -1, r[4], blob(r[5], r[6])))
    cmds = []
    for c in range(h[16]):
        b, i, a, n = struct.unpack_from('<iiqq', d, D + mo + 24 * c); cmds.append((b, i, S(a, ao, 16) if n else -1, n))
    args = [blob(*struct.unpack_from('<qq', d, D + ao + 16 * a)) for a in range(h[18])]
    coffs = [S(q(xo + 8 * i), co, 56) for i in range(h[20])]
    top = struct.unpack_from('<6q', d, D + 0x18)
    name = d[D + top[2]:D + top[2] + 2 * top[3]].decode('utf-16le').rstrip('\0')
    grp = [(g[0], S(g[1], so, 72), g[2]) for g in groups]
    return dict(h=h, hash=bytes(d[0x70:0x80]), groups=grp, states=states, conds=conds, cmds=cmds, args=args, coffs=coffs, name=name)

def write(e, hsh=None):
    gs, st, cs, ms, ar, xs = e['groups'], e['states'], e['conds'], e['cmds'], e['args'], e['coffs']
    go = 72; so = go + 32 * len(gs); co = so + 72 * len(st); mo = co + 56 * len(cs); ao = mo + 24 * len(ms); xo = ao + 16 * len(ar); bo = xo + 8 * len(xs)
    blob = bytearray()
    def put(b):
        if b is None: return -1, 0
        o = bo + len(blob); blob.extend(b); return o, len(b)
    ev = [put(c[5]) for c in cs]; av = [put(a) for a in ar]
    end_blob = bo + len(blob)
    name_off = end_blob + (end_blob & 1); nm = (e['name'] + '\0').encode('utf-16le'); end = name_off + len(nm)
    out = bytearray(D + end)
    hsh = hsh or hashlib.md5(e['name'].encode()).digest()
    struct.pack_into('<i16si', out, D, 1, hsh, 0)
    struct.pack_into('<6q', out, D + 0x18, go, len(gs), name_off, len(nm) // 2, -1, -1)
    for i, (gid, s0, n) in enumerate(gs): struct.pack_into('<4q', out, D + go + 32 * i, gid, so + 72 * s0, n, so + 72 * s0)
    L = lambda i, n, base, size: base + size * i if n else -1
    for i, s in enumerate(st):
        struct.pack_into('<9q', out, D + so + 72 * i, s[0], L(s[1], s[2], xo, 8), s[2], L(s[3], s[4], mo, 24), s[4], L(s[5], s[6], mo, 24), s[6], L(s[7], s[8], mo, 24), s[8])
    for i, c in enumerate(cs):
        struct.pack_into('<7q', out, D + co + 56 * i, -1 if c[0] == -1 else so + 72 * c[0], L(c[1], c[2], mo, 24), c[2], L(c[3], c[4], xo, 8), c[4], *ev[i])
    for i, m in enumerate(ms): struct.pack_into('<iiqq', out, D + mo + 24 * i, m[0], m[1], L(m[2], m[3], ao, 16), m[3])
    for i, a in enumerate(av): struct.pack_into('<qq', out, D + ao + 16 * i, *a)
    for i, c in enumerate(xs): struct.pack_into('<q', out, D + xo + 8 * i, co + 56 * c)
    out[D + bo:D + end_blob] = blob; out[D + name_off:D + end] = nm
    h = list(e['h'])
    h[5] = end; h[10] = len(gs); h[12] = len(st); h[14] = len(cs); h[16] = len(ms); h[18] = len(ar); h[19] = xo; h[20] = len(xs)
    h[21] = end_blob; h[22] = len(nm) // 2; h[23] = h[25] = end; h[24] = h[26] = 0
    struct.pack_into('<27i', out, 0, *h)
    return bytes(out)
