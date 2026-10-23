"""FromSoftware containers used by DS1R (PC and Switch): DCX (DFLT), BND3, BHF3/BDF3, TPF."""
import struct, zlib, sys

def fs_hash(p):   # the game's archive path hash
    h = 0
    for c in p.lower().replace('\\', '/').encode(): h = (h * 37 + c) & 0xffffffff
    return h

def bhd5_entries(bhd):   # {hash: (index offset of entry, size, data offset)}
    h = open(bhd, 'rb').read(); nb, bo = struct.unpack_from('<QQ', h, 0x10); out = {}
    for b in range(nb):
        cnt, _, off = struct.unpack_from('<IIQ', h, bo + b * 16)
        for e in range(cnt):
            hs, sz, o = struct.unpack_from('<IIQ', h, off + e * 16); out[hs] = (off + e * 16, sz, o)
    return out

def undcx(d):
    i = d.find(b'DCA\0'); return d[:i + 8], zlib.decompress(d[i + 8:])

def redcx(head, data, level=6):   # same header, new sizes (DCS uncompressed / compressed, big endian)
    z = zlib.compress(data, level); h = bytearray(head)
    struct.pack_into('>II', h, 0x1c, len(data), len(z)); return bytes(h) + z

def rev8(b): return int(f'{b:08b}'[::-1], 2)

def is_dcx(d): return d[:4] == b'DCX\0'
def maybe_undcx(d): return undcx(d)[1] if is_dcx(d) else d

def bnd3_parse(d, bdt=None):
    """BND3 (data inside) or BHF3 (data in bdt). Returns header info and entries [dict(name,id,off,size,usize,flags,eo)]"""
    mag = d[:4]; assert mag in (b'BND3', b'BHF3'), mag
    fmt, be, bitbe = d[0xc], d[0xd], d[0xe]
    f = fmt if bitbe else rev8(fmt)
    E = '>' if be else '<'
    n = struct.unpack_from(E + 'I', d, 0x10)[0]
    o = 0x20 if mag == b'BND3' else 0x20
    ents = []
    for i in range(n):
        e = dict(eo=o, flags=d[o]); o += 4
        e['size_pos'] = o; e['size'] = struct.unpack_from(E + 'I', d, o)[0]; o += 4
        e['off_pos'] = o
        if f & 0x10: e['off'] = struct.unpack_from(E + 'Q', d, o)[0]; o += 8
        else: e['off'] = struct.unpack_from(E + 'I', d, o)[0]; o += 4
        if f & 2: e['id'] = struct.unpack_from(E + 'i', d, o)[0]; o += 4
        if f & 0xc: no = struct.unpack_from(E + 'I', d, o)[0]; o += 4; e['name'] = d[no:d.index(b'\0', no)].decode('shift_jis', 'replace')
        if f & 0x20: e['usize_pos'] = o; e['usize'] = struct.unpack_from(E + 'I', d, o)[0]; o += 4
        ents.append(e)
    return dict(fmt=f, E=E, n=n, raw_fmt=fmt), ents

def bnd3_files(d, bdt=None):
    h, ents = bnd3_parse(d)
    src = bdt if bdt is not None else d
    return [(e['name'] if 'name' in e else str(e.get('id')), src[e['off']:e['off'] + e['size']]) for e in ents]

def tpf_parse(d):
    assert d[:4] == b'TPF\0', d[:4]
    n = struct.unpack_from('<I', d, 8)[0]; plat = d[0xc]; out = []
    for i in range(n):
        o = 0x10 + i * 20; do, sz, fmt, typ, mips, fl, no, unk = struct.unpack_from('<IIBBBBII', d, o)
        name = d[no:d.index(b'\0', no)].decode('utf-8', 'replace') if d[0xe] != 1 else d[no:d.index(b'\0\0', no) + 1].decode('utf-16le', 'replace')
        out.append(dict(i=i, name=name, off=do, size=sz, fmt=fmt, typ=typ, mips=mips, fl=fl, unk=unk))
    return dict(platform=plat, flag2=d[0xd], enc=d[0xe], n=n), out

DXGI = {71: 'BC1', 72: 'BC1', 74: 'BC2', 77: 'BC3', 78: 'BC3', 80: 'BC4', 83: 'BC5', 98: 'BC7', 99: 'BC7', 28: 'RGBA8', 87: 'BGRA8'}
def dds_info(d):
    assert d[:4] == b'DDS ', d[:4]
    h, w = struct.unpack_from('<II', d, 12); mips = struct.unpack_from('<I', d, 28)[0] or 1
    fourcc = d[84:88]; caps2 = struct.unpack_from('<I', d, 112)[0]
    off = 128; fmt = fourcc.decode('latin1')
    if fourcc == b'DX10': dx = struct.unpack_from('<I', d, 128)[0]; fmt = DXGI.get(dx, f'dxgi{dx}'); off = 148
    else: fmt = {'DXT1': 'BC1', 'DXT3': 'BC2', 'DXT5': 'BC3', 'ATI1': 'BC4', 'ATI2': 'BC5', 'BC4U': 'BC4', 'BC5U': 'BC5'}.get(fmt, fmt if fourcc != b'\0\0\0\0' else 'RGB' + str(struct.unpack_from('<I', d, 88)[0]))
    return dict(w=w, h=h, mips=mips, fmt=fmt, cube=bool(caps2 & 0x200), data_off=off, dxgi=struct.unpack_from('<I', d, 128)[0] if fourcc == b'DX10' else None)

def nvn_hdr(t, e):
    w = struct.unpack_from('<64I', t, e['off'])
    return dict(w=w[16], h=w[17], d=w[18], layers=w[19], nvn=w[20], mips=w[21], size=w[13], target=w[10], bh=w[40], raw=w)

def walk(data, getbdt, path=''):
    """yield (inner path, tpf bytes) for every TPF inside data; getbdt(name) returns the bdt bytes paired with a BHF3"""
    d = maybe_undcx(data)
    m = d[:4]
    if m == b'TPF\0': yield path, d
    elif m == b'BND3':
        for n, x in bnd3_files(d): yield from walk(x, getbdt, path + '|' + n.split('\\')[-1])
    elif m == b'BHF3':
        bdt = getbdt(path)
        if bdt is None: return
        for n, x in bnd3_files(d, bdt): yield from walk(x, getbdt, path + '|' + n.split('\\')[-1])

def _patch(h, E, f, e, off, size):
    struct.pack_into(E + 'I', h, e['size_pos'], size)
    struct.pack_into(E + ('Q' if f & 0x10 else 'I'), h, e['off_pos'], off)
    if 'usize_pos' in e: struct.pack_into(E + 'I', h, e['usize_pos'], size)

def bnd3_rebuild(d, files):
    """BND3 with new file contents (list in entry order); header/names kept, data laid out 16-aligned from the first data offset"""
    h, es = bnd3_parse(d); start = min(e['off'] for e in es); head = bytearray(d[:start]); data = bytearray()
    for e, x in sorted(zip(es, files), key=lambda p: p[0]['off']):
        while (start + len(data)) % 16: data.append(0)
        _patch(head, h['E'], h['fmt'], e, start + len(data), len(x)); data += x
    return bytes(head + data)

def bhf3_rebuild(bhd, bdt, files):
    h, es = bnd3_parse(bhd); head = bytearray(bhd); start = min(e['off'] for e in es); out = bytearray(bdt[:start])
    for e, x in sorted(zip(es, files), key=lambda p: p[0]['off']):
        while len(out) % 16: out.append(0)
        _patch(head, h['E'], h['fmt'], e, len(out), len(x)); out += x
    return bytes(head), bytes(out)
