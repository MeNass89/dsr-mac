"""Decode Switch (NVN block-linear) and PC (DDS) textures to RGBA arrays."""
import struct, numpy as np, texture2ddecoder as T
from fsfmt import nvn_hdr, dds_info
from nvntex import unswizzle_level, levels_geom
NVN = {0x42: ('BC1', 8), 0x43: ('BC2', 16), 0x44: ('BC3', 16), 0x4b: ('BC5', 16), 0x4d: ('BC7', 16), 0x49: ('BC4', 8), 0x6d: ('RGBA8', 4), 0x25: ('RGBA8', 4)}
def decode_bc2(raw, W, H):
    """BC2 = BC1 colour block after an explicit 4-bit alpha block (texture2ddecoder has no BC2): colour decoded as BC1, alpha laid on top. BGRA out, like T."""
    b = np.frombuffer(raw, np.uint8).reshape(-1, 16)
    px = np.frombuffer(T.decode_bc1(b[:, 8:].tobytes(), W, H), np.uint8).reshape(H, W, 4).copy()
    a = b[:, :8]; a = np.stack([a & 15, a >> 4], -1).reshape(H // 4, W // 4, 4, 4) * 17
    px[..., 3] = a.transpose(0, 2, 1, 3).reshape(H, W)
    return px.tobytes()

DEC = {'BC1': T.decode_bc1, 'BC2': T.decode_bc2 if hasattr(T, 'decode_bc2') else decode_bc2, 'BC3': T.decode_bc3, 'BC4': T.decode_bc4, 'BC5': T.decode_bc5, 'BC7': T.decode_bc7}
BPB = {'BC1': 8, 'BC4': 8, 'BC2': 16, 'BC3': 16, 'BC5': 16, 'BC7': 16}

def bgra2rgba(a): return a[..., [2, 1, 0, 3]]

def dec_linear(fmt, raw, W, H):
    if fmt in ('RGBA8', 'BGRA8'):
        a = np.frombuffer(raw[:W * H * 4], np.uint8).reshape(H, W, 4); return a if fmt == 'RGBA8' else bgra2rgba(a)
    bw, bh = max(1, (W + 3) // 4), max(1, (H + 3) // 4)
    px = np.frombuffer(DEC[fmt](raw[:bw * bh * BPB[fmt]], bw * 4, bh * 4), np.uint8).reshape(bh * 4, bw * 4, 4)
    return bgra2rgba(px)[:H, :W]

def sw_level0(t, e):
    h = nvn_hdr(t, e); fmt, bpb = NVN[h['nvn']]; W, H = h['w'], h['h']
    bw, bh = ((W + 3) // 4, (H + 3) // 4) if fmt.startswith('BC') else (W, H)
    geo, _, _ = levels_geom(W, H, 1, bpb, h['bh']) if fmt.startswith('BC') else (None, 0, 0)
    lin = unswizzle_level(t[e['off'] + 0x200:], 0, bw, bh, bpb, geo[0][2])
    return dec_linear(fmt, lin, W, H)

def pc_level0(t, e):
    d = t[e['off']:e['off'] + e['size']]; di = dds_info(d)
    return dec_linear(di['fmt'], d[di['data_off']:], di['w'], di['h']), di
