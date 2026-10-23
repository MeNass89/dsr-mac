"""List and read DS1R (Switch) BHD5/BDT archives: header: bucket count u64 at 0x10, bucket table u64 at 0x18; buckets {count u32, pad, offset u64}, entries {hash, size, offset64}.
usage: bhd5.py <x.bhd5> [scan <bytes-hex>]"""
import struct, sys, mmap, collections
def entries(bhd):
    h = open(bhd, 'rb').read()
    nb, bo = struct.unpack_from('<QQ', h, 0x10)
    out = []
    for b in range(nb):
        cnt, _, off = struct.unpack_from('<IIQ', h, bo + b * 16)
        for e in range(cnt):
            hs, sz, o = struct.unpack_from('<IIQ', h, off + e * 16)
            out.append((hs, sz, o))
    return out
if __name__ == '__main__':
    bhd = sys.argv[1]; bdt = bhd[:-4] + 'bdt'
    es = entries(bhd)
    f = open(bdt, 'rb'); mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
    mags = collections.Counter(mm[o:o + 4] for _, _, o in es)
    print(len(es), 'entries', mags.most_common(15))
    if len(sys.argv) > 3:
        pat = bytes.fromhex(sys.argv[3]); i = mm.find(pat)
        hits = []
        while i >= 0 and len(hits) < 20:
            e = next(((hs, sz, o) for hs, sz, o in es if o <= i < o + sz), None); hits.append((hex(i), e and (hex(e[0]), e[1], hex(e[2]), mm[e[2]:e[2] + 4])))
            i = mm.find(pat, i + 1)
        print(hits)
