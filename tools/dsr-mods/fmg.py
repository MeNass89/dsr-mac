"""FMG (DS1 / DSR text table, version 1, little endian, 32-bit offsets): parse to {id: text or None} and write back."""
import struct

def parse(d):
    assert d[1] == 0 and d[2] == 1, d[:4].hex()
    ng, ns, so = struct.unpack_from('<III', d, 0x0c)   # header 0x1c bytes, then groups of 12 bytes (first string index, first id, last id)
    out = {}
    for g in range(ng):
        oi, a, b = struct.unpack_from('<iii', d, 0x1c + 12 * g)
        for k, i in enumerate(range(a, b + 1)):
            o = struct.unpack_from('<I', d, so + 4 * (oi + k))[0]
            if o == 0: out[i] = None; continue
            e = o
            while True:
                e = d.find(b'\0\0', e)
                if e < 0 or (e - o) % 2 == 0: break
                e += 1
            out[i] = d[o:e].decode('utf-16le')
    return out

def write(ents, unk08=1):
    ids = sorted(ents); groups = []
    for i in ids:
        if groups and i == groups[-1][1] + 1: groups[-1][1] = i
        else: groups.append([i, i])
    ng = len(groups); so = 0x1c + 12 * ng; text = so + 4 * len(ids)
    offs, blob = [], bytearray()
    for i in ids:
        t = ents[i]
        if t is None: offs.append(0); continue
        offs.append(text + len(blob)); blob += t.encode('utf-16le') + b'\0\0'
    h = bytearray(struct.pack('<BBBBIIIIII', 0, 0, 1, 0, 0, unk08, ng, len(ids), so, 0))
    k = 0
    for a, b in groups: h += struct.pack('<iii', k, a, b); k += b - a + 1
    h += struct.pack(f'<{len(ids)}I', *offs); h += blob
    while len(h) % 4: h.append(0)   # files end 4-aligned
    struct.pack_into('<I', h, 4, len(h)); return bytes(h)
