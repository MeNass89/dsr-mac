"""Dark Souls Remastered (Switch) controller glyph sets: PlayStation and Xbox button prompts in place of the Switch ones.

Where the glyphs live (RomFS dvdbnd1): the font icon page DSFont24_1000 (1024x1024, BC3, Tegra block linear) inside /font/<lang>/DSFont24_h.tpf.dcx, and its
684x684 copy DSFont24_1000_l (10 mips) inside /font/<lang>/DSFont24.tpf.dcx, for the 7 font languages (14 archives); the FMG text tags (<?conclusion?>,
<?cancel?> ...) draw from that page. The inventory tab hints (small L / R / ZL / ZR keycaps) sit in Menu11 of /menu/menu.tpf.dcx and /menu/menu_1.tpf.dcx.
The game has no other glyph set. This tool repaints the face, +/-, shoulder and D-pad glyphs inside the game's own rings and writes the archives as a mod
folder (archive paths, the layout the launcher's mod system takes; _hash/<8 hex> = an archive known only by its path hash). Sticks, stick clicks, the (R)/(C) marks and the item icons are left as they are.

Face glyphs follow the host's mapping (dm/host/front_gamepad.m): by position (default) the Switch A glyph is the right button (PlayStation circle, Xbox B),
B the bottom (cross, Xbox A), X the top (triangle, Xbox Y), Y the left (square, Xbox X); by label A = Xbox A / cross, B = Xbox B / circle, X = Xbox X /
square, Y = Xbox Y / triangle. Game semantics are untouched: only the pictures change.

usage: python -I dsr_glyphs.py <RomFS dir> <out dir> [sets...]      sets: ps-position ps-label xbox-position xbox-label (default all)
       python -I dsr_glyphs.py overlay <RomFS dir> <set dir> <overlay dir>   (rig: bhd5 + bdt.append, what the launcher builds)
needs numpy, pillow, scipy, etcpak."""
import sys, os, struct, zlib, io
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage as nd
import etcpak

FONT_ARCHIVES = [f'/font/{l}/DSFont24{s}.tpf.dcx' for l in ('english', 'japanese', 'korean', 'polish', 'russian', 'tchinese', 'schinese') for s in ('', '_h')]
MENU_ARCHIVES = ['#597c48dd', '/menu/menu_1.tpf.dcx']   # the full menu atlas archive's name is not recovered: '#hash' = by FS hash (the game's path hash)
SETS = ['ps-position', 'ps-label', 'xbox-position', 'xbox-label']

def fs_hash(p):
    h = 0
    for c in p.lower().replace('\\', '/').encode(): h = (h * 37 + c) & 0xffffffff
    return h

# ---- archives -------------------------------------------------------------------------------------------------------------------------------------
def bhd5_entries(bhd):   # {hash: (index offset of entry, size, data offset)}
    h = open(bhd, 'rb').read(); nb, bo = struct.unpack_from('<QQ', h, 0x10); out = {}
    for b in range(nb):
        cnt, _, off = struct.unpack_from('<IIQ', h, bo + b * 16)
        for e in range(cnt):
            hs, sz, o = struct.unpack_from('<IIQ', h, off + e * 16); out[hs] = (off + e * 16, sz, o)
    return out

def path_hash(p): return int(p[1:], 16) if p.startswith('#') else fs_hash(p)

def read_file(romfs, path):
    hs = path_hash(path)
    for a in (0, 1):
        es = bhd5_entries(f'{romfs}/dvdbnd{a}.bhd5')
        if hs in es:
            _, sz, o = es[hs]; f = open(f'{romfs}/dvdbnd{a}.bdt', 'rb'); f.seek(o); return f.read(sz)
    raise KeyError(path)

def undcx(d):
    i = d.find(b'DCA\0'); return d[:i + 8], zlib.decompress(d[i + 8:])

def redcx(head, data):   # same header, new sizes (DCS uncompressed / compressed, big endian)
    z = zlib.compress(data, 9); h = bytearray(head)
    struct.pack_into('>II', h, 0x1c, len(data), len(z)); return bytes(h) + z

def tpf_entries(d):
    n = struct.unpack_from('<I', d, 8)[0]; out = []
    for i in range(n):
        o = 0x10 + i * 20; do, sz, fmt, typ, mips, fl, no, _ = struct.unpack_from('<IIBBBBII', d, o)
        out.append(dict(name=d[no:d.index(b'\0', no)].decode(), off=do, size=sz, fmt=fmt))
    return out

# ---- Tegra block linear + BC3 -----------------------------------------------------------------------------------------------------------------------
def block_height(hb):
    bh = 16
    while bh > 1 and hb <= (bh // 2) * 8: bh //= 2
    return bh

def swizzle_offsets(wb, hb, bpe):
    bh = block_height(hb); gobs_x = (wb * bpe + 63) // 64
    ys, xs = np.mgrid[0:hb, 0:wb]; xb = xs * bpe; xi = xb % 64; yi = ys % 8
    base = (((ys // (8 * bh)) * gobs_x + xb // 64) * bh + (ys % (8 * bh)) // 8) * 512
    off = base + (xi // 32) * 256 + (yi // 2) * 64 + ((xi % 32) // 16) * 32 + (yi % 2) * 16 + (xi % 16)
    size = gobs_x * 64 * (-(-hb // (8 * bh)) * 8 * bh)
    return off, size

def deswizzle(raw, wb, hb, bpe):
    off, _ = swizzle_offsets(wb, hb, bpe); a = np.frombuffer(raw, np.uint8)
    return np.stack([a[off + k] for k in range(bpe)], -1)

def swizzle(lin, wb, hb, bpe):
    off, size = swizzle_offsets(wb, hb, bpe); out = np.zeros(size, np.uint8)
    for k in range(bpe): out[off + k] = lin[..., k]
    return out.tobytes()

def bc3_decode(raw, W, H):
    bw, bhb = (W + 3) // 4, (H + 3) // 4; blk = deswizzle(raw, bw, bhb, 16)
    a0 = blk[..., 0].astype(np.float32); a1 = blk[..., 1].astype(np.float32)
    p8 = np.stack([a0, a1] + [((6 - i) * a0 + (1 + i) * a1) / 7 for i in range(6)], -1)
    p6 = np.stack([a0, a1] + [((4 - i) * a0 + (1 + i) * a1) / 5 for i in range(4)] + [a0 * 0, a0 * 0 + 255], -1)
    pal = np.where((a0 > a1)[..., None], p8, p6); bits = np.zeros(blk.shape[:-1], np.uint64)
    for i in range(6): bits |= blk[..., 2 + i].astype(np.uint64) << np.uint64(8 * i)
    alpha = np.take_along_axis(pal, np.stack([(bits >> np.uint64(3 * i)) & np.uint64(7) for i in range(16)], -1).astype(np.int64), -1)
    c0 = blk[..., 8].astype(np.uint32) | blk[..., 9].astype(np.uint32) << 8; c1 = blk[..., 10].astype(np.uint32) | blk[..., 11].astype(np.uint32) << 8
    rgb = lambda c: np.stack([(c >> 11 & 31) * 255 // 31, (c >> 5 & 63) * 255 // 63, (c & 31) * 255 // 31], -1).astype(np.float32)
    e0, e1 = rgb(c0), rgb(c1); cp = np.stack([e0, e1, (2 * e0 + e1) / 3, (e0 + 2 * e1) / 3], -2)
    idx = sum(blk[..., 12 + i].astype(np.uint32) << (8 * i) for i in range(4))
    col = np.take_along_axis(cp, np.stack([(idx >> (2 * i)) & 3 for i in range(16)], -1)[..., None].repeat(3, -1).astype(np.int64), -2)
    px = np.concatenate([col, alpha[..., None]], -1).reshape(bhb, bw, 4, 4, 4).transpose(0, 2, 1, 3, 4).reshape(bhb * 4, bw * 4, 4)
    return np.clip(px, 0, 255).astype(np.uint8)[:H, :W].copy()

def bc3_encode(img):   # RGBA uint8 HxW -> swizzled BC3 bytes
    H, W = img.shape[:2]; bw, bhb = (W + 3) // 4, (H + 3) // 4
    pad = np.zeros((bhb * 4, bw * 4, 4), np.uint8); pad[:H, :W] = img
    lin = np.frombuffer(etcpak.compress_bc3(pad.tobytes(), bw * 4, bhb * 4), np.uint8).reshape(bhb, bw, 16)
    return swizzle(lin, bw, bhb, 16)

def tex_dims(d, t):   # nvn texture header words: width 16, height 17, levels 21, data size 13, data at +0x200
    w = struct.unpack_from('<24I', d, t['off']); return w[16], w[17], w[21], w[13]

def get_tex(d, name):
    t = next(t for t in tpf_entries(d) if t['name'] == name); W, H, L, ds = tex_dims(d, t)
    return t, W, H, L, bc3_decode(d[t['off'] + 0x200: t['off'] + 0x200 + ds], W, H)

def put_tex(d, t, img, levels):
    d = bytearray(d); W, H, L, ds = tex_dims(d, t); assert L == levels and img.shape[:2] == (H, W)
    out = b''; im = Image.fromarray(img); w, h = W, H
    for i in range(L):
        lv = img if i == 0 else np.array(premul_resize(im, (w, h)))
        out += bc3_encode(lv); w, h = max(1, w // 2), max(1, h // 2)
    assert len(out) == ds, (len(out), ds)
    d[t['off'] + 0x200: t['off'] + 0x200 + ds] = out; return bytes(d)

def premul_resize(im, size):   # alpha-correct downscale (no dark halos around the glyphs)
    a = np.array(im).astype(np.float32); a[..., :3] *= a[..., 3:] / 255
    r = np.stack([np.array(Image.fromarray(a[..., k]).resize(size, Image.LANCZOS)) for k in range(4)], -1)
    r[..., :3] /= np.maximum(r[..., 3:], 1e-3) / 255
    return Image.fromarray(np.clip(r, 0, 255).astype(np.uint8))

# ---- drawing --------------------------------------------------------------------------------------------------------------------------------------
SS = 8   # supersampling
SF = '/System/Library/Fonts/SFNSRounded.ttf'
COL = dict(tri=(70, 210, 170), cir=(240, 85, 95), crs=(110, 160, 235), sq=(225, 120, 205),
           xa=(110, 200, 70), xb=(235, 70, 60), xx=(60, 140, 235), xy=(245, 200, 40))
WHITE = (250, 250, 250)

def font(px, weight=b'Heavy'):
    f = ImageFont.truetype(SF, px)
    try: f.set_variation_by_name(weight)
    except Exception: pass
    return f

def canvas(n): return Image.new('RGBA', (n * SS, n * SS), (0, 0, 0, 0))

def text_layer(n, s, col, height, width=None, dy=0):
    """s centred in an n x n layer, cap height `height` px, squeezed to `width` px if needed"""
    im = canvas(n); dr = ImageDraw.Draw(im); f = font(int(height * SS * 1.42))
    x0, y0, x1, y1 = dr.textbbox((0, 0), s, font=f); tw, th = x1 - x0, y1 - y0
    t = Image.new('RGBA', (tw + 8, th + 8), (0, 0, 0, 0)); ImageDraw.Draw(t).text((4 - x0, 4 - y0), s, font=f, fill=col + (255,))
    sc = height * SS / th
    nw = tw * sc
    if width and nw > width * SS: nw = width * SS
    t = t.resize((max(1, int(nw + 8 * sc)), int((th + 8) * sc)), Image.LANCZOS)
    im.alpha_composite(t, ((n * SS - t.width) // 2, (n * SS - t.height) // 2 + int(dy * SS))); return im

def ps_symbol(n, kind, col, r=9.0, lw=2.6):
    im = canvas(n); dr = ImageDraw.Draw(im); c = n * SS / 2; R = r * SS; W = int(lw * SS)
    if kind == 'cir': dr.ellipse([c - R, c - R, c + R, c + R], outline=col + (255,), width=W)
    elif kind == 'sq': q = R * 0.86; dr.rectangle([c - q, c - q, c + q, c + q], outline=col + (255,), width=W)
    elif kind == 'tri':
        q = R * 1.12; pts = [(c, c - q), (c + q * 0.866, c + q * 0.5), (c - q * 0.866, c + q * 0.5)]
        dr.line(pts + [pts[0], pts[1]], fill=col + (255,), width=W, joint='curve')
    elif kind == 'crs':
        q = R * 0.80
        for a, b in (((c - q, c - q), (c + q, c + q)), ((c - q, c + q), (c + q, c - q))): dr.line([a, b], fill=col + (255,), width=W)
        for p in ((c - q, c - q), (c + q, c + q), (c - q, c + q), (c + q, c - q)): dr.ellipse([p[0] - W / 2, p[1] - W / 2, p[0] + W / 2, p[1] + W / 2], fill=col + (255,))
    return im

def icon(n, kind, col):
    im = canvas(n); dr = ImageDraw.Draw(im); c = n * SS / 2; S = SS; F = col + (255,)
    if kind == 'menu':   # three lines (PlayStation OPTIONS, Xbox Menu)
        for k in (-1, 0, 1): dr.rounded_rectangle([c - 8 * S, c + k * 5.2 * S - 1.3 * S, c + 8 * S, c + k * 5.2 * S + 1.3 * S], radius=1.3 * S, fill=F)
    elif kind == 'view':   # Xbox View: two overlapping windows
        dr.rounded_rectangle([c - 8 * S, c - 6.5 * S, c + 3 * S, c + 2.5 * S], radius=1.5 * S, outline=F, width=int(2.2 * S))
        dr.rounded_rectangle([c - 3 * S, c - 2.5 * S, c + 8 * S, c + 6.5 * S], radius=1.5 * S, outline=F, width=int(2.2 * S))
    elif kind == 'create':   # PlayStation CREATE / SHARE: a small upward arrow out of an open box
        w = int(2.4 * S)
        dr.line([(c - 8 * S, c - 1 * S), (c - 8 * S, c + 7 * S), (c + 8 * S, c + 7 * S), (c + 8 * S, c - 1 * S)], fill=F, width=w, joint='curve')
        dr.line([(c, c + 3 * S), (c, c - 8 * S)], fill=F, width=w)
        dr.line([(c - 5 * S, c - 3.5 * S), (c, c - 8.8 * S), (c + 5 * S, c - 3.5 * S)], fill=F, width=w, joint='curve')
    return im

def down(im, n): return np.array(premul_resize(im, (n, n)))

# ---- glyph page edit ------------------------------------------------------------------------------------------------------------------------------
CELL = 50   # hi page grid: glyph k of a row is centred at x = 30 + 50k, y = 25 + 50*row (rows 0-3)
def cell_box(row, col): return 30 + 50 * col - 25, 25 + 50 * row + (0 if row == 0 else 1) - 25

def interior(alpha, thick):
    sh = alpha > 120; fill = nd.binary_fill_holes(sh); return nd.binary_erosion(fill, iterations=thick)

def repaint(page, row, col, layer, thick=4, bg=(8, 4, 8), keep_outline=True):
    """clear the inside of the glyph (inside its outline ring) to bg, then draw layer (RGBA n x n, already downsampled) clipped to that inside"""
    x, y = cell_box(row, col); n = CELL
    sub = page[y:y + n, x:x + n].astype(np.float32)
    inner = interior(sub[..., 3], thick)
    soft = nd.gaussian_filter(inner.astype(np.float32), 0.6)
    sub[..., :3] = sub[..., :3] * (1 - soft[..., None]) + np.array(bg, np.float32) * soft[..., None]
    la = layer.astype(np.float32); a = la[..., 3:] / 255 * soft[..., None]
    sub[..., :3] = sub[..., :3] * (1 - a) + la[..., :3] * a
    page[y:y + n, x:x + n] = np.clip(sub, 0, 255).astype(np.uint8)

def symbol_colour(page, row, col):   # the original letter colour (white, or grey on the dark +/- variants)
    x, y = cell_box(row, col); sub = page[y:y + 50, x:x + 50]
    inner = interior(sub[..., 3], 5); lum = sub[..., :3].mean(-1)
    v = lum[inner]; return tuple(int(c) for c in sub[inner][v >= np.percentile(v, 97)][:, :3].mean(0))

def dpad(page, row, col, light):
    """replace the four-circle glyph by a D-pad cross; `light` = which arms the original highlighted ('u','d','l','r') and its highlight colour"""
    x, y = cell_box(row, col); n = CELL; on, colr = light
    im = canvas(n); dr = ImageDraw.Draw(im); c = n * SS / 2; S = SS; arm = 7.0 * S; L = 20.0 * S
    cross = [(c - arm, c - L), (c + arm, c - L), (c + arm, c - arm), (c + L, c - arm), (c + L, c + arm), (c + arm, c + arm), (c + arm, c + L),
             (c - arm, c + L), (c - arm, c + arm), (c - L, c + arm), (c - L, c - arm), (c - arm, c - arm)]
    dr.polygon(cross, fill=(250, 250, 250, 255))                                   # outer outline like the game's rings
    g = 2.4 * S; inner = [(px + (g if px < c else -g if px > c else 0), py + (g if py < c else -g if py > c else 0)) for px, py in cross]
    dr.polygon(inner, fill=(8, 4, 8, 255))
    tip = 4.2 * S
    e = arm - g * 1.6; far = L - g * 1.6; near = arm + 0.8 * S   # highlighted arm: inside of the arm, from near the centre to its tip
    arms = {'u': [c - e, c - far, c + e, c - near], 'd': [c - e, c + near, c + e, c + far], 'l': [c - far, c - e, c - near, c + e], 'r': [c + near, c - e, c + far, c + e]}
    for k in on: dr.rectangle(arms[k], fill=colr + (255,))
    dr.ellipse([c - 2 * S, c - 2 * S, c + 2 * S, c + 2 * S], fill=(70, 70, 70, 255))
    lay = down(im, n)
    sub = page[y:y + n, x:x + n]; sub[:] = 0; sub[:] = lay

def dpad_state(page, row, col):
    x, y = cell_box(row, col); sub = page[y:y + 50, x:x + 50].astype(int); c = 25; d = 13
    pts = {'u': (c, c - d), 'd': (c, c + d), 'l': (c - d, c), 'r': (c + d, c)}
    lum = {k: sub[py - 2:py + 3, px - 2:px + 3, :3].mean() for k, (px, py) in pts.items()}
    on = [k for k, v in lum.items() if v > 60]
    colr = tuple(int(v) for v in sub[pts[on[0]][1], pts[on[0]][0], :3]) if on else WHITE
    return on, colr

# face mapping: Switch glyph -> what to draw. position = host default
FACE = {
    'ps-position':   {'A': ('ps', 'cir'), 'B': ('ps', 'crs'), 'X': ('ps', 'tri'), 'Y': ('ps', 'sq')},
    'ps-label':      {'A': ('ps', 'crs'), 'B': ('ps', 'cir'), 'X': ('ps', 'sq'), 'Y': ('ps', 'tri')},
    'xbox-position': {'A': ('xb', 'B'), 'B': ('xb', 'A'), 'X': ('xb', 'Y'), 'Y': ('xb', 'X')},
    'xbox-label':    {'A': ('xb', 'A'), 'B': ('xb', 'B'), 'X': ('xb', 'X'), 'Y': ('xb', 'Y')},
}
SHOULDER = {'ps': ['L1', 'R1', 'L2', 'R2'], 'xbox': ['LB', 'RB', 'LT', 'RT']}
PLUSMINUS = {'ps': ('menu', 'create'), 'xbox': ('menu', 'view')}

def face_layer(kind, what):
    if kind == 'ps': return down(ps_symbol(CELL, what, COL[what]), CELL)
    return down(text_layer(CELL, what, COL['x' + what.lower()], 19.5, dy=0.3), CELL)

def edit_page(page, setname):
    fam = setname.split('-')[0]; page = page.copy()
    for col, sw in enumerate('YXBA'): repaint(page, 0, col, face_layer(*FACE[setname][sw]))
    for (row, col), which in {(0, 4): 1, (0, 5): 0, (3, 16): 1, (3, 15): 0}.items():   # - then + ; row 3 = dark variants
        colr = symbol_colour(page, row, col); repaint(page, row, col, down(icon(CELL, PLUSMINUS[fam][which], colr), CELL), bg=(8, 4, 8) if row == 0 else (20, 20, 20))
    for k, s in enumerate(SHOULDER[fam]):   # L R ZL ZR tabs
        repaint(page, 0, 6 + k, down(text_layer(CELL, s, WHITE, 15.5, width=26, dy=2.5), CELL), thick=3)
    states = [(r, c, dpad_state(page, r, c)) for r, c in [(0, k) for k in range(12, 19)] + [(3, k) for k in range(8, 15)]]
    for r, c, st in states: dpad(page, r, c, st)
    return page

KEYCAPS = [((529, 327, 572, 364), 0), ((552, 386, 595, 423), 1), ((520, 454, 562, 498), 2), ((570, 454, 612, 498), 3)]   # Menu11: L, R, ZL, ZR keycaps
def edit_menu11(img, setname):
    fam = setname.split('-')[0]; img = img.copy()
    for (x0, y0, x1, y1), k in KEYCAPS:
        sub = img[y0:y1, x0:x1].astype(np.float32); h, w = sub.shape[:2]
        inner = interior(sub[..., 3], 3); soft = nd.gaussian_filter(inner.astype(np.float32), 0.6)
        sub[..., :3] = sub[..., :3] * (1 - soft[..., None]) + 250 * soft[..., None]
        n = max(w, h); lay = text_layer(n, SHOULDER[fam][k], (10, 10, 10), n * 0.42, width=w * 0.62, dy=n * 0.06)
        lay = np.array(premul_resize(lay, (n, n)))[(n - h) // 2:(n - h) // 2 + h, (n - w) // 2:(n - w) // 2 + w].astype(np.float32)
        a = lay[..., 3:] / 255 * soft[..., None]; sub[..., :3] = sub[..., :3] * (1 - a) + lay[..., :3] * a
        img[y0:y1, x0:x1] = np.clip(sub, 0, 255).astype(np.uint8)
    return img

# ---- build --------------------------------------------------------------------------------------------------------------------------------------
def build(romfs, out, sets):
    hi_src = None; arch = {}
    for p in FONT_ARCHIVES + MENU_ARCHIVES: arch[p] = undcx(read_file(romfs, p))
    _, _, _, _, hi_src = get_tex(arch['/font/english/DSFont24_h.tpf.dcx'][1], 'DSFont24_1000')
    _, _, _, _, m11_src = get_tex(arch['/menu/menu_1.tpf.dcx'][1], 'Menu11')
    for s in sets:
        page = edit_page(hi_src, s); low = np.array(premul_resize(Image.fromarray(page), (684, 684)))
        m11 = edit_menu11(m11_src, s)
        os.makedirs(f'{out}/{s}', exist_ok=True)
        Image.fromarray(page).save(f'{out}/{s}.preview.png')
        for p, (head, d) in arch.items():
            if p in MENU_ARCHIVES: t, W, H, L, _ = get_tex(d, 'Menu11'); d = put_tex(d, t, m11, L)
            elif p.endswith('_h.tpf.dcx'): t, W, H, L, _ = get_tex(d, 'DSFont24_1000'); d = put_tex(d, t, page, L)
            else: t, W, H, L, _ = get_tex(d, 'DSFont24_1000_l'); d = put_tex(d, t, low, L)
            dst = f'{out}/{s}' + (p if p.startswith('/') else f'/_hash/{p[1:]}'); os.makedirs(os.path.dirname(dst), exist_ok=True); open(dst, 'wb').write(redcx(head, d))
        print('built', s, flush=True)

def overlay(romfs, setdir, ov):   # same result as the launcher's buildOverlay for one mod folder
    os.makedirs(ov, exist_ok=True)
    for a in (0, 1):
        bhd = bytearray(open(f'{romfs}/dvdbnd{a}.bhd5', 'rb').read()); es = bhd5_entries(f'{romfs}/dvdbnd{a}.bhd5')
        base = os.path.getsize(f'{romfs}/dvdbnd{a}.bdt'); app = bytearray()
        for root, _, files in os.walk(setdir):
            for fn in files:
                rel = '/' + os.path.relpath(os.path.join(root, fn), setdir); hs = int(fn, 16) if rel.startswith('/_hash/') else fs_hash(rel)
                if hs not in es: continue
                data = open(os.path.join(root, fn), 'rb').read()
                while len(app) % 16: app.append(0)
                eo = es[hs][0]; struct.pack_into('<IQ', bhd, eo + 4, len(data), base + len(app)); app += data
        if app: open(f'{ov}/dvdbnd{a}.bhd5', 'wb').write(bhd); open(f'{ov}/dvdbnd{a}.bdt.append', 'wb').write(app)

if __name__ == '__main__':
    if sys.argv[1] == 'overlay': overlay(*sys.argv[2:5])
    else: build(sys.argv[1], sys.argv[2], sys.argv[3:] or SETS)
