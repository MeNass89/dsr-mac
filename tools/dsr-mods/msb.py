# DS1 MSB (map layout) in both builds: PC 32-bit offsets / 4-byte alignment, Switch 64-bit offsets / 8-byte alignment.
# Each entry is a fixed header (offset fields 'o', 4-byte fields 'i') and data blocks the header points into (relative to the entry start).
import struct
SPEC = {'MODEL_PARAM_ST': 'oiioiiii', 'EVENT_PARAM_ST': 'oiiiooi', 'POINT_PARAM_ST': 'oiiiiiiiiiooooi', 'PARTS_PARAM_ST': 'oiiio' + 'i' * 17 + 'ooi'}
HDR8 = {'MODEL_PARAM_ST': 40, 'EVENT_PARAM_ST': 48, 'POINT_PARAM_ST': 88, 'PARTS_PARAM_ST': 176}
STR = {'MODEL_PARAM_ST': (0, 1), 'EVENT_PARAM_ST': (0,), 'POINT_PARAM_ST': (0,), 'PARTS_PARAM_ST': (0, 1)}   # which offset fields are strings (by order)

def _r(d, o, W): return int.from_bytes(d[o:o + W], 'little', signed=True)
def _al(n, a): return -(-n // a) * a

def hdr_layout(spec, W):
    pos = 0; out = []
    for c in spec:
        if c == 'o': pos = _al(pos, W); out.append(('o', pos)); pos += W
        else: out.append(('i', pos)); pos += 4
    return out, pos

def parse(d, W):
    params = []; o = 0
    while True:
        no, n = _r(d, o + W, W), _r(d, o + 2 * W, W)
        offs = [_r(d, o + 3 * W + W * i, W) for i in range(n - 1)]; nxt = _r(d, o + 3 * W + W * (n - 1), W)
        name = d[no:d.index(b'\0', no)].decode()
        ends = offs[1:] + [nxt or len(d)]
        lay, hsz = hdr_layout(SPEC[name], W)
        ents = []
        for e, end in zip(offs, ends):
            vals = [('o', _r(d, e + p, W)) if k == 'o' else ('i', d[e + p:e + p + 4]) for k, p in lay]
            extra = d[e + hsz:e + (HDR8[name] if W == 8 else hsz)]
            ptrs = sorted({v for k, v in vals if k == 'o' and v})
            blocks = {}
            for j, p in enumerate(ptrs):
                q = ptrs[j + 1] if j + 1 < len(ptrs) else end - e
                blocks[p] = d[e + p:e + q]
            si = [i for i, (k, _) in enumerate(vals) if k == 'o']
            strs = {si[k] for k in STR[name]}
            ent = {'vals': [], 'extra': bytes(extra)}
            for i, (k, v) in enumerate(vals):
                if k == 'i': ent['vals'].append(v); continue
                if not v: ent['vals'].append(None); continue
                b = blocks[v]
                ent['vals'].append(('s', b[:b.index(b'\0') + 1]) if i in strs else ('b', b))
            ents.append(ent)
        params.append((name, ents))
        if not nxt: break
        o = nxt
    return params

def write(params, W):
    out = bytearray()
    def P(v): return v.to_bytes(W, 'little', signed=True)
    for pi, (name, ents) in enumerate(params):
        base = len(out)
        out += P(0); nf = len(out); out += P(0); out += P(len(ents) + 1)
        tab = len(out); out += b'\0' * (W * len(ents)); nxt = len(out); out += P(0)
        out[nf:nf + W] = P(len(out)); out += name.encode() + b'\0'
        while len(out) % W: out += b'\0'
        lay, hsz = hdr_layout(SPEC[name], W)
        for k, ent in enumerate(ents):
            e = len(out); out[tab + W * k:tab + W * (k + 1)] = P(e)
            h = bytearray(HDR8[name] if W == 8 else hsz)
            out += h
            if W == 8 and ent['extra']: out[e + hsz:e + HDR8[name]] = ent['extra']
            for (kind, p), v in zip(lay, ent['vals']):
                if kind == 'i': out[e + p:e + p + 4] = v
            for (kind, p), v in zip(lay, ent['vals']):
                if kind != 'o' or v is None: continue
                t, b = v
                if t == 'b': 
                    while len(out) % W: out += b'\0'
                out[e + p:e + p + W] = P(len(out) - e)
                if t == 's': out += b
                if t == 's' and W == 4 and name == 'PARTS_PARAM_ST' and p == lay[[i for i, (k2, _) in enumerate(lay) if k2 == 'o'][1]][1]:
                    while len(out) % 4: out += b'\0'
                    while len(out) - e - hsz < 0x14: out += b'\0'   # PC parts: the two names take at least 0x14 bytes
                elif t == 'b': out += b
            while len(out) % W: out += b'\0'
        if pi + 1 < len(params): out[nxt:nxt + W] = P(len(out))
    return bytes(out)

TYPE_AT = {'MODEL_PARAM_ST': 1, 'EVENT_PARAM_ST': 2, 'PARTS_PARAM_ST': 1, 'POINT_PARAM_ST': 3}
Z = b'\0\0\0\0'
def _block_to_switch(name, typ, i, b):
    """PC data block -> Switch data block (learned from the 17 maps both builds share; every other block keeps its size)"""
    if name == 'EVENT_PARAM_ST' and i == 5:
        if typ in (0, 2) and len(b) == 4: return b + Z
        if typ == 4 and len(b) == 52: return Z + Z + b[4:8] + Z + b[8:48] + b[48:52] + Z   # treasure: part index widened, lots, flags
    if name == 'PARTS_PARAM_ST' and i == 23 and typ in (1, 9) and len(b) == 24: return Z + b + Z
    if name == 'POINT_PARAM_ST' and i in (10, 11, 12, 13) and len(b) in (4, 12): return b + Z
    return b

def to_switch(params):
    out = []
    for name, ents in params:
        hsz = hdr_layout(SPEC[name], 8)[1]
        ne = []
        for e in ents:
            typ = struct.unpack('<i', e['vals'][TYPE_AT[name]])[0]
            vals = [v if not (isinstance(v, tuple) and v[0] == 'b') else ('b', _block_to_switch(name, typ, i, v[1])) for i, v in enumerate(e['vals'])]
            ne.append({'vals': vals, 'extra': b'\0' * (HDR8[name] - hsz)})
        out.append((name, ne))
    return out
