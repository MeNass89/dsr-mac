# FMOD sound banks: Switch frpg_main.bank = FMOD Studio RIFF bank around an FSB5 of FADPCM samples; PC frpg_main.fsb = FSB4 of MP3 samples.
import struct, numpy as np
FREQ = {0: 4000, 1: 8000, 2: 11000, 3: 11025, 4: 16000, 5: 22050, 6: 24000, 7: 32000, 8: 44100, 9: 48000, 10: 96000}
COEF = np.array([[0, 0], [60, 0], [122, 60], [115, 52], [98, 55]], np.int64)

def fsb5(b):
    v, ns, shs, nms, dsz, mode = struct.unpack_from('<IIIIII', b, 4); o = 0x3c; out = []
    for k in range(ns):
        q = struct.unpack_from('<Q', b, o)[0]; o += 8; nxt = q & 1; chunks = []
        while nxt:
            c = struct.unpack_from('<I', b, o)[0]; nxt = c & 1; sz = (c >> 1) & 0xffffff; chunks.append((c >> 25, b[o + 4:o + 4 + sz])); o += 4 + sz
        out.append(dict(freq=FREQ[(q >> 1) & 15], ch=[1, 2, 6, 8][(q >> 5) & 3], off=((q >> 7) & 0x7ffffff) << 5, n=q >> 34, chunks=chunks, raw=q))
    no = 0x3c + shs
    for k, s in enumerate(out):
        x = no + struct.unpack_from('<I', b, no + 4 * k)[0]; s['name'] = b[x:b.index(b'\0', x)].decode()
    data = 0x3c + shs + nms
    for k, s in enumerate(out):
        end = out[k + 1]['off'] if k + 1 < len(out) else dsz
        s['data'] = b[data + s['off']:data + end]
    return dict(mode=mode, samples=out, head=b[:0x3c], dsz=dsz, shs=shs, nms=nms)

def fadpcm_decode(d, n):
    out = []; h1 = h2 = 0
    for f in range(0, len(d) - 0x8b, 0x8c):
        coefs, shifts = struct.unpack_from('<II', d, f); h1, h2 = struct.unpack_from('<hh', d, f + 8)
        for i in range(8):
            c1, c2 = COEF[((coefs >> 4 * i) & 15) % 7] if ((coefs >> 4 * i) & 15) % 7 < 5 else (0, 0)
            sh = 22 - ((shifts >> 4 * i) & 15)
            for j in range(4):
                nib = struct.unpack_from('<I', d, f + 0xc + 0x10 * i + 4 * j)[0]
                for k in range(8):
                    s = ((((nib >> 4 * k) & 15) << 28) & 0xffffffff)
                    s = (s - (1 << 32) if s >= 1 << 31 else s) >> sh
                    s = (s - h2 * c2 + h1 * c1) >> 6
                    s = max(-32768, min(32767, s)); out.append(s); h2, h1 = h1, s
    return np.array(out[:n], np.int16)

def fsb4(p):
    n, sh, ds, ver, mode = struct.unpack_from('<iiiII', p, 4); o = 0x30; data = 0x30 + sh; out = []
    for k in range(n):
        sz = struct.unpack_from('<H', p, o)[0]; name = p[o + 2:o + 32].split(b'\0')[0].decode()
        nsamp, clen, ls, le, smode, freq = struct.unpack_from('<IIIIIi', p, o + 32)
        out.append(dict(name=name, n=nsamp, mode=smode, freq=freq, ch=struct.unpack_from('<H', p, o + 0x3e)[0], data=p[data:data + clen])); data += clen; o += sz
    return out

_BR = {1: [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320], 2: [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160]}
def mp3_frames(d):
    """FSB4 MP3 samples pad every frame to 4 bytes (FMOD's alignment): give back plain consecutive frames"""
    o = 0; out = bytearray()
    while o + 4 <= len(d):
        if d[o] != 0xff or d[o + 1] & 0xe0 != 0xe0: o += 1; continue
        v1 = (d[o + 1] >> 3) & 3 == 3; br = _BR[1 if v1 else 2][d[o + 2] >> 4]
        sr = [44100, 48000, 32000][(d[o + 2] >> 2) & 3] // (1 if v1 else 2); pad = (d[o + 2] >> 1) & 1
        if not br: o += 1; continue
        n = (144000 if v1 else 72000) * br // sr + pad
        out += d[o:o + n]; o += n; o += -o % 4
    return bytes(out)

def fadpcm_encode(pcm):
    """int16 mono samples -> FADPCM frames (0x8c bytes per 256 samples), the decoder's inverse: per 32-sample subframe the predictor
    (5 filters) and shift code k (a nibble q decodes to q << k plus the prediction) with the least squared error"""
    x = np.concatenate([np.asarray(pcm, np.int64), np.zeros(-len(pcm) % 256, np.int64)])
    out = bytearray(); h1 = h2 = 0
    for f in range(0, len(x), 256):
        coefs = shifts = 0; body = bytearray(); fh1, fh2 = h1, h2
        for i in range(8):
            seg = [int(v) for v in x[f + 32 * i:f + 32 * i + 32]]; best = None
            for ci in range(5):
                c1, c2 = int(COEF[ci][0]), int(COEF[ci][1])
                for k in range(13):
                    s1, s2 = h1, h2; nib = []; err = 0
                    for v in seg:
                        p = (s1 * c1 - s2 * c2) >> 6
                        q = max(-8, min(7, round((v - p) / (1 << k))))
                        rec = max(-32768, min(32767, ((q << (6 + k)) - s2 * c2 + s1 * c1) >> 6))
                        err += (v - rec) ** 2; nib.append(q & 15); s2, s1 = s1, rec
                        if best is not None and err >= best[0]: break
                    else:
                        best = (err, ci, k, nib, s1, s2)
            _, ci, k, nib, h1, h2 = best
            coefs |= ci << 4 * i; shifts |= k << 4 * i
            for j in range(4):
                w = 0
                for m in range(8): w |= nib[8 * j + m] << 4 * m
                body += struct.pack('<I', w)
        out += struct.pack('<IIhh', coefs, shifts, fh1, fh2) + body
    return bytes(out)

def fadpcm_encode_ch(pcm):
    """(samples, channels) int16 -> FADPCM with channel frames interleaved"""
    pcm = np.asarray(pcm); pcm = pcm[:, None] if pcm.ndim == 1 else pcm
    chans = [fadpcm_encode(pcm[:, c]) for c in range(pcm.shape[1])]
    return b''.join(ch[i:i + 0x8c] for i in range(0, len(chans[0]), 0x8c) for ch in chans)

def fsb5_replace(b, new):
    """FSB5 bytes with some samples replaced: new = {index: (pcm int16 (n, ch) at the sample's own rate)}; header fields rewritten"""
    v, ns, shs, nms, dsz, mode = struct.unpack_from('<IIIIII', b, 4)
    F = fsb5(b); hdr = bytearray(b[:0x3c + shs]); names = b[0x3c + shs:0x3c + shs + nms]
    data = bytearray(); o = 0x3c
    for k, s in enumerate(F['samples']):
        q = struct.unpack_from('<Q', hdr, o)[0]
        if k in new:
            pcm = np.asarray(new[k]); pcm = pcm[:, None] if pcm.ndim == 1 else pcm
            blob = fadpcm_encode_ch(pcm); n = pcm.shape[0]
            peak = float(np.abs(pcm).max()) / 32768 if pcm.size else 0.0
        else: blob = s['data']; n = s['n']; peak = None
        blob += b'\0' * (-len(blob) % 32)
        q = (q & ((1 << 7) - 1)) | ((len(data) >> 5) << 7) | (n << 34)
        struct.pack_into('<Q', hdr, o, q); oc = o + 8; nxt = q & 1
        while nxt:
            c = struct.unpack_from('<I', hdr, oc)[0]; nxt = c & 1; sz = (c >> 1) & 0xffffff
            if c >> 25 == 13 and peak is not None: struct.pack_into('<f', hdr, oc + 4, min(1.0, peak))
            oc += 4 + sz
        o = oc; data += blob
    struct.pack_into('<I', hdr, 0x14, len(data))
    return bytes(hdr) + names + bytes(data)

def bank_replace(bank, new):
    """FMOD Studio .bank (RIFF 'FEV '): the FSB5 in its SND chunk replaced, RIFF / SND / SNDH sizes fixed"""
    i = bank.find(b'FSB5'); snd = bank.rfind(b'SND ', 0, i)
    fsb_new = fsb5_replace(bank[i:], new)
    pad = i - (snd + 8)                                   # alignment bytes between the SND chunk header and the FSB5
    out = bytearray(bank[:snd]) + b'SND ' + struct.pack('<I', pad + len(fsb_new)) + bank[snd + 8:i] + fsb_new
    struct.pack_into('<I', out, 4, len(out) - 8)
    h = out.find(b'SNDH')
    if h >= 0: struct.pack_into("<I", out, h + 16, len(fsb_new))   # SNDH: offset of the FSB5 in the file, its size
    return bytes(out)

def ffmpeg():
    import shutil, os
    f = shutil.which('ffmpeg') or next((p for p in ('/opt/homebrew/bin/ffmpeg', '/usr/local/bin/ffmpeg') if os.path.exists(p)), None)
    if f is None: raise ValueError('ffmpeg is needed for sounds and movies (brew install ffmpeg)')
    return f

def mp3_pcm(data, rate, ch):
    import subprocess
    r = subprocess.run([ffmpeg(), '-v', 'quiet', '-f', 'mp3', '-i', '-', '-f', 's16le', '-ac', str(ch), '-ar', str(rate), '-'], input=mp3_frames(data), capture_output=True)
    if r.returncode: raise ValueError('ffmpeg could not decode the MP3 sample')
    return np.frombuffer(r.stdout, np.int16).reshape(-1, ch)

def port_fsb4(pc, bank, base=None):
    """PC FSB4 sound bank (a mod's frpg_main.fsb) onto the Switch .bank: every sample whose PC data differs from base (the PC original, when the mod
    ships it) or, without base, every sample, re-encoded at the Switch sample's rate and channel count. Returns (bank, names replaced)."""
    P = fsb4(pc); B = {s['name'].lower(): s['data'] for s in fsb4(base)} if base else {}
    i = bank.find(b'FSB5'); S = fsb5(bank[i:])['samples']; idx = {s['name'].lower(): k for k, s in enumerate(S)}
    new = {}; names = []
    for p in P:
        key = p['name'].lower().rsplit('.', 1)[0]
        if key not in idx or (B and B.get(p['name'].lower()) == p['data']): continue
        s = S[idx[key]]; new[idx[key]] = mp3_pcm(p['data'], s['freq'], s['ch']); names.append(p['name'])
    return (bank_replace(bank, new) if new else None), names
