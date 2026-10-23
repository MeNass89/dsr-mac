"""Write every GLSLC compiler output found in DS1R's BHD5/BDT archives (DCX zlib → BND3 → shader binaries) to <out>/<sha16>.glslc,
the capture-folder format shader_split.py reads with shader_glslc_capture on. usage: dsr_glslc.py <RomFS> <out dir>"""
import sys, os, zlib, mmap, struct, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bhd5
romfs, out = sys.argv[1:3]; os.makedirs(out, exist_ok=True)
MAG = b'\x91\x68\x86\x19'; n = 0; seen = set()
for name in sorted(f for f in os.listdir(romfs) if f.endswith('.bhd5')):
    f = open(os.path.join(romfs, name[:-4] + 'bdt'), 'rb'); mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
    for _, s, o in bhd5.entries(os.path.join(romfs, name)):
        d = mm[o:o + s]
        if d[:4] == b'DCX\0':
            try: d = zlib.decompress(d[0x4c:])
            except zlib.error: continue
        i = d.find(MAG)
        while i >= 0:
            size = struct.unpack_from('<I', d, i + 0x44)[0] if i + 0x48 <= len(d) else 0
            if 0x760 < size <= len(d) - i:
                blob = d[i:i + size]; k = hashlib.sha256(blob).hexdigest()[:16]
                if k not in seen:
                    seen.add(k); open(os.path.join(out, k + '.glslc'), 'wb').write(blob); n += 1
            i = d.find(MAG, i + 1)
print(n, 'unique GLSLC outputs written to', out)
