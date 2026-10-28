# DS1 TAE (0x1000B) animation event files (time act events): PC 32-bit offsets, Switch 64-bit (every offset and count widened to 8 bytes, same order, no padding).
# parse(d, W) -> plain dict; write(t, W) lays it out again. W = 4 (PC) or 8 (Switch).
import struct

def _r(d, o, W): return int.from_bytes(d[o:o + W], 'little', signed=True)

def parse(d, W):
    H = 0x20 if W == 4 else 0x30   # start of the fixed 0x20-byte block after the four header varints
    hdr_const = d[H:H + 0x20]
    flags = d[H + 0x20:H + 0x30]
    tid, ac = struct.unpack_from('<ii', d, H + 0x30)
    ao = _r(d, H + 0x38, W)
    sk_off = _r(d, ao - 0 if False else 0, W)
    names_at = {4: 0x98, 8: 0xd8}[W]
    sk, sib = _r(d, names_at, W), _r(d, names_at + W, W)
    def u16(o):
        e = o
        while e < len(d) and d[e:e + 2] != b'\0\0': e += 2
        return d[o:e].decode('utf-16le')
    nexts = [_r(d, _r(d, ao + 2 * W * a + W, W) + 6 * W, W) for a in range(ac)]
    anims = []
    for a in range(ac):
        aid, bo = _r(d, ao + 2 * W * a, W), _r(d, ao + 2 * W * a + W, W)
        ec, eh, gc, go, tc, to, af = [_r(d, bo + W * i, W) for i in range(7)]
        mtype = _r(d, af, W); nm_off = _r(d, af + 2 * W, W); mini = d[af + 3 * W:af + 3 * W + 8]
        name_at = af + 3 * W + 8 + (8 if mtype == 1 else W)   # zero padding after the mini header: 8 bytes for an import, one varint otherwise
        nxt = min([x for x in (eh if ec else 0, to if tc else 0, go if gc else 0, len(d)) if x > af] + [x for x in nexts if x > af])
        name = bytes(d[name_at:nxt])   # file name (UTF-16), an empty one, or nothing: kept as raw bytes
        times = [struct.unpack_from('<f', d, to + 4 * i)[0] for i in range(tc)] if tc else []
        evs = []
        datas = []
        for e in range(ec):
            s, en, do = [_r(d, eh + 3 * W * e + W * i, W) for i in range(3)]
            evs.append([(s - to) // 4, (en - to) // 4, struct.unpack_from('<i', d, do)[0]]); datas.append(do)
        groups = []
        for g in range(gc):
            cnt, vo, ty = [_r(d, go + 3 * W * g + W * i, W) for i in range(3)]
            idx = [(struct.unpack_from('<i', d, vo + 4 * i)[0] - eh) // (3 * W) for i in range(cnt)]
            groups.append((_r(d, ty, W), idx))
        anims.append(dict(id=aid, mtype=mtype, mini=bytes(mini), name=name, times=times, evs=evs, datas=datas, groups=groups, go=go, eh=eh))
    # event parameters: from after an event's header to the next event's data (or whatever follows the last one)
    starts = sorted({x for an in anims for x in an['datas']} | {an['go'] for an in anims if an['go']} | {_r(d, _r(d, ao + 2 * W * a + W, W) + 6 * W, W) for a in range(ac)} | {len(d)})
    for an in anims:
        for ev, do in zip(an['evs'], an['datas']):
            p = do + 4 + (4 if W == 8 else 0) + W
            nxt = next(x for x in starts if x > do)
            ev.append(bytes(d[p:nxt]))
        del an['datas'], an['go'], an['eh']
    return dict(hdr=bytes(hdr_const), flags=bytes(flags), id=tid, sk=u16(sk), sib=u16(sib), anims=anims, consts=d)

def write(t, W):
    P = lambda v: v.to_bytes(W, 'little', signed=True)
    out = bytearray()
    out += b'TAE \0\0\0\0' + struct.pack('<iI', 0x1000B, 0)
    out += P(0x40 if W == 4 else 0x50) + P(1) + P(0x50 if W == 4 else 0x60) + P(0x70 if W == 4 else 0x98)
    out += t['hdr'] + t['flags']
    anims = sorted(t['anims'], key=lambda a: a['id'])
    out += struct.pack('<ii', t['id'], len(anims))
    fix = {}
    def res(k): fix[k] = len(out); out.extend(b'\0' * W)
    def fill(k, v): out[fix[k]:fix[k] + W] = P(v)
    res('anims'); res('groups')
    if W == 4: out += P(0x90) + P(len(anims)); res('first'); out += P(0) + P(1) + P(0x80) + b'\0' * 8
    else: out += P(0xc8) + P(len(anims)); res('first'); out += P(0) + P(1) + P(0xb0) + b'\0' * 8
    out += struct.pack('<ii', t['id'], t['id'])
    if W == 4: out += P(0x50) + b'\0' * 8 + P(0x98)
    else: out += P(0x60) + b'\0' * 16 + P(0xd8)
    res('sk'); res('sib'); out += P(0)
    if W == 4: out += P(0)
    fill('sk', len(out)); out += (t['sk'] + '\0').encode('utf-16le')
    fill('sib', len(out)); out += (t['sib'] + '\0').encode('utf-16le')
    fill('anims', len(out) if anims else 0)
    for i, a in enumerate(anims): out += P(a['id']); res(f'a{i}')
    fill('groups', len(out)); res('gc'); res('go'); g0 = len(out); n = 0; i = 0
    while i < len(anims):
        j = i
        while j + 1 < len(anims) and anims[j + 1]['id'] == anims[j]['id'] + 1: j += 1
        out += struct.pack('<ii', anims[i]['id'], anims[j]['id']); out += P(fix[f'a{i}'] - W); n += 1; i = j + 1
    fill('gc', n); fill('go', g0 if n else 0)
    fill('first', len(out) if anims else 0)
    for i, a in enumerate(anims):
        fill(f'a{i}', len(out))
        for k in ('ec', 'eh', 'gc', 'go', 'tc', 'to', 'af'): res(f'{k}{i}')
        fill(f'ec{i}', len(a['evs'])); fill(f'gc{i}', len(a['groups'])); fill(f'tc{i}', len(a['times']))
    for i, a in enumerate(anims):
        fill(f'af{i}', len(out)); out += P(a['mtype']); out += P(len(out) + W); res('nm'); out += a['mini'] + b'\0' * (8 if a['mtype'] == 1 else W)
        fill('nm', len(out))
        out += a['name']
        to = len(out); fill(f'to{i}', to if a['times'] else 0)
        for x in a['times']: out += struct.pack('<f', x)
        eh = len(out); fill(f'eh{i}', eh if a['evs'] else 0)
        for j, ev in enumerate(a['evs']): out += P(to + 4 * ev[0]) + P(to + 4 * ev[1]); res(f'e{i}:{j}')
        for j, ev in enumerate(a['evs']):
            fill(f'e{i}:{j}', len(out)); out += struct.pack('<i', ev[2]) + (b'\0' * 4 if W == 8 else b''); out += P(len(out) + W if ev[3] or W == 4 else 0); out += ev[3]   # the Switch files point nowhere (0) when an event has no parameters
        fill(f'go{i}', len(out) if a['groups'] else 0)
        for j, g in enumerate(a['groups']): out += P(len(g[1])); res(f'gv{i}:{j}'); res(f'gt{i}:{j}')
        for j, g in enumerate(a['groups']):
            fill(f'gt{i}:{j}', len(out)); out += P(g[0]); fill(f'gv{i}:{j}', len(out))
            for k in g[1]: out += struct.pack('<i', eh + 3 * W * k)
    struct.pack_into('<I', out, 12, len(out))
    return bytes(out)

def _evkey(a):
    t = a['times']
    return sorted((round(t[e[0]], 4) if t else 0, round(t[e[1]], 4) if t else 0, e[2]) for e in a['evs'])

def port(pc, sw):
    """PC mod TAE (32-bit) onto the Switch TAE of the same name: an animation whose event list matches the Switch one keeps the Switch animation
    (the Switch build tuned some parameters); one the mod changed is taken from the PC file, its event parameters cut to the Switch length of that
    event type. Returns (Switch-layout bytes, ids of the animations taken from the mod)."""
    p, s = parse(pc, 4), parse(sw, 8)
    plen = {}
    for a in s['anims']:
        for e in a['evs']: plen.setdefault(e[2], len(e[3]))
    S = {a['id']: a for a in s['anims']}; out = []; taken = []
    for a in p['anims']:
        b = S.get(a['id'])
        if b is not None and _evkey(a) == _evkey(b): out.append(b); continue
        a = dict(a, evs=[[e[0], e[1], e[2], (e[3] + b'\0' * 16)[:plen.get(e[2], len(e[3]))]] for e in a['evs']])
        if b is not None: a['name'] = b['name']
        out.append(a); taken.append(a['id'])
    return write(dict(s, anims=out), 8), taken
