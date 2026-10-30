"""Build the clawd-on-desk 'honami' theme from sheet-A-<ver>.png / sheet-B-<ver>.png (3x2 grid, green screen).
Read-only on the sheets; writes only into the output dir.
Usage: py -3.14 build_honami_theme.py [--sheet v5] [--raw dir] [--out theme_dir] [--quality 75] [--preview png]

Steps: slice cells -> chroma key with green unmixing (keeps the white outline, no green fringe)
-> drop stray blobs from neighbour cells -> paste B's eye region onto A (feathered mask)
-> scale + align by feet baseline -> procedural animation (breathing / sway / hop / blink,
all about the feet) -> animated WebP -> theme.json (+ idle mini-animations from cell 1).
"""
import argparse, json, math
from collections import deque
from pathlib import Path
import numpy as np
from PIL import Image, ImageFilter, ImageDraw

HERE = Path(__file__).resolve().parent
RAW = HERE.parent / 'honami' / 'raw'
OUT = HERE.parent / 'honami-theme'
PREVIEW = HERE.parent / 'honami-preview.png'

CELL = 512
FRAME_MS = 70
TARGET_H = 400          # idle figure height in px after scaling
MARGIN = 12
MOUSE_SLEEP_MS = 300000        # 5 min without mouse -> sleeping
CELLS = {'idle': 0, 'thinking': 1, 'working': 2, 'notification': 3, 'attention': 4, 'sleeping': 5}
BLINKABLE = {'idle', 'thinking', 'working', 'notification'}


# ---------------------------------------------------------------- keying
def key_green(rgb):
    """rgb HxWx3 uint8 -> float32 HxWx4 (unmixed colour, alpha 0..255)."""
    f = rgb.astype(np.float32)
    border = np.concatenate([f[0], f[-1], f[:, 0], f[:, -1]])
    dom = border[:, 1] - np.maximum(border[:, 0], border[:, 2])
    bg = np.median(border[dom > 150], axis=0)               # measured, not assumed #00FF00
    gbg = bg[1] - max(bg[0], bg[2])
    t = (f[..., 1] - np.maximum(f[..., 0], f[..., 2])) / gbg
    a = np.clip((0.97 - t) / (0.97 - 0.06), 0, 1)           # t<0.06 opaque, t>0.97 transparent
    a[t <= 0.06] = 1.0
    a[a < 0.02] = 0.0
    fg = np.clip((f - (1 - a)[..., None] * bg) / np.maximum(a, 1e-3)[..., None], 0, 255)  # pix=a*fg+(1-a)*bg
    edge = (a < 0.999) & (a > 0)
    cap = np.maximum(fg[..., 0], fg[..., 2]) + 6            # residual green spill on edge pixels
    fg[..., 1] = np.where(edge, np.minimum(fg[..., 1], cap), fg[..., 1])
    out = np.dstack([fg, a * 255]).astype(np.float32)
    out[a == 0, :3] = 0
    return out


def drop_specks(rgba, min_area=250):
    """Remove small disconnected blobs: noise, and neighbour-cell hair tips crossing the grid lines.
    Blobs touching the cell border must be >= 3000 px (the figure itself is far bigger)."""
    al = rgba[..., 3] > 8
    near = np.asarray(Image.fromarray(al.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(9))) > 0
    h, w = near.shape
    seen = np.zeros_like(near)
    keep = np.zeros_like(near)
    for y0 in range(h):
        for x0 in range(w):
            if near[y0, x0] and not seen[y0, x0]:
                comp, dq = [], deque([(y0, x0)])
                seen[y0, x0] = True
                while dq:
                    y, x = dq.popleft(); comp.append((y, x))
                    for yy, xx in ((y+1, x), (y-1, x), (y, x+1), (y, x-1)):
                        if 0 <= yy < h and 0 <= xx < w and near[yy, xx] and not seen[yy, xx]:
                            seen[yy, xx] = True; dq.append((yy, xx))
                ys, xs = zip(*comp)
                cnt = int(al[ys, xs].sum())
                touches = min(ys) == 0 or min(xs) == 0 or max(ys) == h - 1 or max(xs) == w - 1
                if cnt >= min_area and not (touches and cnt < 3000):
                    keep[ys, xs] = True
    out = rgba.copy()
    out[~keep] = 0
    return out


def eye_mask(a_rgb, b_rgb, alpha):
    """Soft 0..1 mask of where B's closed eyes differ from A."""
    d = np.abs(a_rgb.astype(np.int16) - b_rgb.astype(np.int16)).max(axis=2)
    m = Image.fromarray(((d > 60) & (alpha > 0.5)).astype(np.uint8) * 255)
    m = m.filter(ImageFilter.MedianFilter(5))               # scattered re-encode noise
    m = m.filter(ImageFilter.MaxFilter(11))                 # cover whole eye incl. lashes
    m = m.filter(ImageFilter.MinFilter(3))
    arr = np.asarray(m, dtype=np.uint8)
    ys, xs = np.nonzero(arr)                                # keep only the face area (drop far-away specks)
    cy, cx = int(np.median(ys)), int(np.median(xs))
    box = np.zeros_like(arr); box[max(cy - 50, 0):cy + 50, max(cx - 110, 0):cx + 110] = 1
    m = Image.fromarray(arr * box).filter(ImageFilter.GaussianBlur(2.5))   # feather
    return np.asarray(m, dtype=np.float32) / 255.0


# ---------------------------------------------------------------- image helpers (premultiplied float)
def to_img(arr):
    return Image.fromarray(np.clip(arr + 0.5, 0, 255).astype(np.uint8), 'RGBA')


def premult(arr):
    a = np.array(arr, dtype=np.float32)
    a[..., :3] *= a[..., 3:4] / 255.0
    return a


def unpremult(a):
    out = a.copy()
    out[..., 3] = np.clip(out[..., 3], 0, 255)
    out[..., :3] = np.clip(out[..., :3], 0, out[..., 3:4])
    al = np.maximum(out[..., 3:4], 1e-3)
    out[..., :3] = out[..., :3] / al * 255.0
    out[out[..., 3] < 1, :3] = 0
    return to_img(np.clip(out, 0, 255))


def bbox(img, thr=16):
    return img.getchannel('A').point(lambda v: 255 if v > thr else 0).getbbox()


def resize_pm(pm, size):
    return np.dstack([np.asarray(Image.fromarray(pm[..., i], 'F').resize(size, Image.LANCZOS), dtype=np.float32)
                      for i in range(4)])


class Sprite:
    """Premultiplied float planes of one pose (+ optional blink version) with a foot anchor."""
    def __init__(self, base_pm, blink_pm, foot=None):
        self.planes = {'o': [Image.fromarray(base_pm[..., i], 'F') for i in range(4)]}
        if blink_pm is not None:
            self.planes['b'] = [Image.fromarray(blink_pm[..., i], 'F') for i in range(4)]
        al = base_pm[..., 3]
        ys, xs = np.nonzero(al > 16)
        y1 = ys.max()
        low = al[int(y1 - 0.3 * (y1 - ys.min())):y1 + 1]
        self.foot = (float((low.sum(axis=0) * np.arange(low.shape[1])).sum() / max(low.sum(), 1)), float(y1))
        if foot is not None:
            self.foot = foot
        self.xfix = 0.0                 # constant sideways shift (e.g. to put this pose's head over the idle head)
        self.size = al.shape[::-1]
        # sparse silhouette points (for canvas extent calculation)
        self.pts = np.stack([xs[::5], ys[::5]], axis=1).astype(np.float32)
        self.box = (xs.min(), ys.min(), xs.max() + 1, y1 + 1)

    def head_x(self):
        """x of the head centre (middle of the hair extent 60 px below the crown, source-cell px scaled), in sprite pixels."""
        k = self.size[0] / CELL
        a = np.asarray(self.planes['o'][3]) > 128
        y0 = int(np.nonzero(a.sum(axis=1) >= 100 * k)[0].min())
        xs = np.nonzero(a[y0 + int(60 * k)])[0]
        return float(xs.min() + xs.max()) / 2

    def map_points(self, p, anchor):
        sx, sy, dx, dy, rot = p
        dx = dx + self.xfix
        c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))
        q = (self.pts - np.array(self.foot)) * np.array([sx, sy])
        x = q[:, 0] * c - q[:, 1] * s
        y = q[:, 0] * s + q[:, 1] * c
        return x + anchor[0] + dx, y + anchor[1] + dy

    def render(self, p, canvas, anchor, blink=False):
        sx, sy, dx, dy, rot = p
        dx = dx + self.xfix
        c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))
        ax, ay = anchor[0] + dx, anchor[1] + dy
        fx, fy = self.foot
        # canvas -> sprite:  F + S^-1 R^-1 (q - A)
        ia, ib, ic, id_ = c / sx, s / sx, -s / sy, c / sy
        coeffs = (ia, ib, fx - (ia * ax + ib * ay), ic, id_, fy - (ic * ax + id_ * ay))
        planes = self.planes['b' if blink and 'b' in self.planes else 'o']
        res = np.dstack([np.asarray(pl.transform(canvas, Image.AFFINE, coeffs, Image.BICUBIC), dtype=np.float32)
                         for pl in planes])
        return unpremult(res)


# ---------------------------------------------------------------- motion
def smooth(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


def env(t, a, b, c, d):
    """0 -> 1 on [a,b], hold to c, 1 -> 0 on [c,d]."""
    if t < a or t > d: return 0.0
    if t < b: return smooth((t - a) / (b - a))
    if t <= c: return 1.0
    return 1 - smooth((t - c) / (d - c))


def hop_pose(u, height, squash):
    """u in 0..1 within one hop: landing squash -> air -> anticipation squash. Returns (sx, sy, dy)."""
    if u < 0.15:
        sq = squash * math.sin(math.pi * u / 0.15); h = 0.0
    elif u > 0.85:
        sq = 0.5 * squash * math.sin(math.pi * (u - 0.85) / 0.15); h = 0.0
    else:
        sq = 0.0; h = math.sin(math.pi * (u - 0.15) / 0.7)
    return 1 + 0.6 * sq - 0.012 * h, 1 - sq + 0.025 * h, -height * h


def blinks(*starts, ln=3):
    out = set()
    for s0 in starts:
        out.update(range(s0, s0 + ln))
    return out


def anim_spec(name):
    """-> (frame count, params(i) -> (sx, sy, dx, dy, rot), set of blink frame indices)."""
    H = TARGET_H
    if name == 'idle':      # 7 s loop: breath 3 % (2 cycles) + sway +-1.5 deg; blinks: single, single, double
        n = 100
        def f(i):
            t = i / n; p = 0.5 - 0.5 * math.cos(4 * math.pi * t)
            return (1 - 0.01 * p, 1 + 0.03 * p, 0, 0, 1.5 * math.sin(2 * math.pi * t))
        return n, f, blinks(16) | blinks(56) | blinks(82, 88)
    if name == 'thinking':  # 7 s loop: slow head tilt left/right (+-3 deg about the feet), light breath
        n = 100
        def f(i):
            t = i / n; p = 0.5 - 0.5 * math.cos(4 * math.pi * t)
            return (1 - 0.004 * p, 1 + 0.015 * p, 0, 0, 3.0 * math.sin(2 * math.pi * t))
        return n, f, blinks(10) | blinks(44, 50) | blinks(80)
    if name == 'working':   # quiet: breath 2 % only, no bobbing / squash
        n = 100
        def f(i):
            p = 0.5 - 0.5 * math.cos(4 * math.pi * i / n)
            return (1 - 0.006 * p, 1 + 0.02 * p, 0, 0, 0)
        return n, f, blinks(22) | blinks(56, 62) | blinks(90)
    if name == 'notification':  # 3 hops (9 % of height, landing squash), then eyes blink while it waits
        n = 72
        def f(i):
            t = i / n; act = 0.46
            if t >= act: return (1, 1, 0, 0, 0)
            sx, sy, dy = hop_pose((t / act * 3) % 1.0, 0.09 * H, 0.08)
            return (sx, sy, 0, dy, 0)
        return n, f, blinks(42) | blinks(58, 62, ln=2)
    if name == 'attention':     # 3 cheerful hops, 10 %
        n = 44
        def f(i):
            t = i / n; act = 0.92
            if t >= act: return (1, 1, 0, 0, 0)
            sx, sy, dy = hop_pose((t / act * 3) % 1.0, 0.10 * H, 0.09)
            return (sx, sy, 0, dy, 2.0 * math.sin(2 * math.pi * t * 3))
        return n, f, set()
    if name == 'sleeping':      # slow, deeper breathing (4 %)
        n = 72
        def f(i):
            p = 0.5 - 0.5 * math.cos(2 * math.pi * i / n)
            return (1 - 0.012 * p, 1 + 0.04 * p, 0, 0, 0)
        return n, f, set()
    # ---- idle mini-animations (all start and end at rest pose)
    if name == 'idle_tilt':     # head tilt +-5 deg, hold, back
        n = 26
        def f(i):
            e = env(i / n, 0.08, 0.35, 0.62, 0.92)
            return (1, 1, 0, 0, 5.0 * e)
        return n, f, blinks(13)
    if name == 'idle_look':     # look right, then left (shift + turn)
        n = 34
        def f(i):
            v = math.sin(2 * math.pi * i / n)
            return (1, 1, 0.035 * H * v, 0, 3.0 * v)
        return n, f, blinks(15)
    if name == 'idle_hop':      # one small hop
        n = 16
        def f(i):
            sx, sy, dy = hop_pose(i / n, 0.075 * H, 0.07)
            return (sx, sy, 0, dy, 0)
        return n, f, set()
    if name == 'idle_stretch':  # stretch up with eyes closed
        n = 36
        def f(i):
            e = env(i / n, 0.1, 0.42, 0.6, 0.9)
            return (1 - 0.03 * e, 1 + 0.08 * e, 0, 0, 0)
        return n, f, {i for i in range(n) if env(i / n, 0.1, 0.42, 0.6, 0.9) > 0.9}
    if name == 'idle_read':     # ~8.4 s: sit down (T poses) -> read (2 blinks, page, head-up smile) -> stand up (reverse)
        n = DOWN_TICKS + READ_TICKS + DOWN_TICKS
        def f(i):
            j = i - DOWN_TICKS
            if not 0 <= j < READ_TICKS:
                return (1, 1, 0, 0, 0)                           # transitions: positions are set per node
            p = 0.5 - 0.5 * math.cos(2 * math.pi * j / 44)       # breath, 2 cycles, rest at both ends of the reading part
            return (1 - 0.005 * p, 1 + 0.015 * p, SIT_DX, 0, 0)
        return n, f, set()
    raise KeyError(name)


STATE_ANIMS = ['idle', 'thinking', 'working', 'notification', 'attention', 'sleeping']
IDLE_ANIMS = ['idle_tilt', 'idle_pat','idle_look', 'idle_hop', 'idle_stretch', 'idle_read']
SPRITE_OF = {n: n for n in STATE_ANIMS}
SPRITE_OF.update({n: 'idle' for n in IDLE_ANIMS})
SPRITE_OF['idle_read'] = 'idle_read'



# ---------------------------------------------------------------- sit-down / reading sheets (sheet-T, sheet-S)
# sheet-S cells: 0 read, 1 page turn, 2 look up + smile, 3 eyes closed.  sheet-T cells: 0 stand with closed book,
# 1 half squat, 2 sit with closed book, 3 sit with book half open.  Everything is registered onto S cell 0
# (scale, dx, dy about SIT_RF; found once by alpha-silhouette search):
SIT_RF = (300.0, 478.0)
REGS = {'page': ('S', 1, (1.005, 20.5, 0.0)), 'smile': ('S', 2, (1.0, 0.0, 28.0)), 'blink': ('S', 3, (1.01, 20.0, 29.0)),
        't3': ('T', 2, (0.99, 4.0, 26.5)), 't4': ('T', 3, (1.005, 20.5, 28.5))}
SIT_FOOT = (316.5, 479.0)        # S cell 0: bbox centre x, bottom row (ground line)
SIT_SCALE = 0.99                 # head width matches the standing figure (hair width at head level 0.98-1.0); same for T
SIT_TARGET = (256.0, 479.0)      # where the foot point lands in the 512 frame before the common resize
SIT_SHIFT = 0.12                 # sitting figure is placed this fraction of the canvas width right of centre
HEAD_ELLIPSE = (285, 200, 150, 130)   # cx, cy, rx, ry in S cell 0 coordinates: whole head incl. bangs, not the long hair below
STAND_FRAC = {'T1': 0.2, 'T2': 0.55}  # horizontal path (0 = standing centre, 1 = sitting centre) of the two standing key poses
SIT_DX = 0                       # px; set in main() so the sitting figure centre lands ~62 % across the canvas
PAT_SCALE = (0.93,) * 6          # sheet-H is drawn ~8 % larger than the idle figure (hair width 408 vs 376 px)


def warp_aff(plane, A, F, T):
    """forward map q = T + A*(p - F) (uniform scale A), bicubic, 512x512 output."""
    c = 1 / A
    coeffs = (c, 0, F[0] - c * T[0], 0, c, F[1] - c * T[1])
    return np.asarray(Image.fromarray(plane, 'F').transform((CELL, CELL), Image.AFFINE, coeffs, Image.BICUBIC), dtype=np.float32)


def patch_mask(a_rgba, b_rgba, box, thr=60, med=5, grow=11, feather=2.5):
    """Soft mask where cell b differs from cell a inside box (x0,y0,x1,y1)."""
    d = np.abs(a_rgba[..., :3] - b_rgba[..., :3]).max(axis=2) * (np.maximum(a_rgba[..., 3], b_rgba[..., 3]) > 128)
    x0, y0, x1, y1 = box
    sel = np.zeros_like(d, dtype=bool); sel[y0:y1, x0:x1] = True
    m = Image.fromarray(((d > thr) & sel).astype(np.uint8) * 255)
    m = m.filter(ImageFilter.MedianFilter(med)).filter(ImageFilter.MaxFilter(grow)).filter(ImageFilter.MinFilter(3))
    arr = np.asarray(m, dtype=np.uint8) * sel
    return np.asarray(Image.fromarray(arr).filter(ImageFilter.GaussianBlur(feather)), dtype=np.float32) / 255.0


def cut6(sheet_rgb):
    """3 columns x 2 rows of 512 px cells (1536x1024 sheet) -> keyed cells."""
    return [drop_specks(key_green(sheet_rgb[r * CELL:(r + 1) * CELL, c * CELL:(c + 1) * CELL])) for r in range(2) for c in range(3)]


def cut_cells(sheet_rgb):
    return [drop_specks(key_green(sheet_rgb[r * CELL:(r + 1) * CELL, c * CELL:(c + 1) * CELL])) for r in range(2) for c in range(2)]


class ReadSprites:
    """Cell 0 of the sitting sheet is the base; blink / page-turn / head swap (smile) / closed-book (t3) / half-open
    book (t4) are pasted in locally after registration, mixed in premultiplied space. The two standing key poses
    (T cells 0 and 1) are whole cells. Variants are cached by weight tuple."""
    EYES = (185, 205, 355, 300)
    BOOK = (170, 290, 395, 420)
    BOOK2 = (140, 270, 420, 450)
    ORDER = ('t3', 't4', 'page', 'smile', 'blink')

    def __init__(self, sheet_s, sheet_t, size, k):
        S, T = cut_cells(sheet_s), cut_cells(sheet_t)
        src = {'S': S, 'T': T}
        self.size, self.k = size, k

        def reg_cell(key):
            sh, idx, r = REGS[key]
            return premult(src[sh][idx]), r
        # registered onto S0 (S0 coordinates), only for building masks
        regf = {}
        for key in REGS:
            pm, (sc, dx, dy) = reg_cell(key)
            regf[key] = np.asarray(unpremult(np.dstack([warp_aff(pm[..., j], sc, SIT_RF, (SIT_RF[0] + dx, SIT_RF[1] + dy)) for j in range(4)])), dtype=np.float32)
        base = np.asarray(to_img(S[0]), dtype=np.float32)
        m = {'blink': patch_mask(base, regf['blink'], self.EYES),
             'page': patch_mask(base, regf['page'], self.BOOK, grow=21, feather=5),
             't3': patch_mask(base, regf['t3'], self.BOOK2, grow=21, feather=5),
             't4': patch_mask(base, regf['t4'], self.BOOK2, grow=21, feather=5)}
        el = Image.new('L', (CELL, CELL), 0)
        cx, cy, rx, ry = HEAD_ELLIPSE
        ImageDraw.Draw(el).ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=255)
        m['smile'] = np.asarray(el.filter(ImageFilter.GaussianBlur(22)), dtype=np.float32) / 255.0
        self.debug_masks = m

        # final: single resampling of each cell into the target frame (registration + common scale)
        def final_of(pm, sc, dx, dy):
            T_ = (SIT_TARGET[0] + SIT_SCALE * (SIT_RF[0] + dx - SIT_FOOT[0]), SIT_TARGET[1] + SIT_SCALE * (SIT_RF[1] + dy - SIT_FOOT[1]))
            return np.dstack([warp_aff(pm[..., j], SIT_SCALE * sc, SIT_RF, T_) for j in range(4)])
        self.final = {'base': final_of(premult(S[0]), 1.0, 0.0, 0.0)}
        for key in REGS:
            pm, (sc, dx, dy) = reg_cell(key)
            self.final[key] = final_of(pm, sc, dx, dy)
        self.masks = {key: warp_aff(v.astype(np.float32), SIT_SCALE, SIT_FOOT, SIT_TARGET) for key, v in m.items()}
        # standing key poses: whole cells, same scale, feet (bbox centre x, bottom row) on the ground line
        self.stand_pose = []
        for c in T[:2]:
            ys, xs = np.nonzero(c[..., 3] > 16)
            F = (float(xs.min() + xs.max() + 1) / 2, float(ys.max()))
            pm = premult(c)
            self.stand_pose.append(Sprite(resize_pm(np.dstack([warp_aff(pm[..., j], SIT_SCALE, F, SIT_TARGET) for j in range(4)]), size),
                                          None, foot=(SIT_TARGET[0] * k, SIT_TARGET[1] * k)))
        self.foot = (SIT_TARGET[0] * k, SIT_TARGET[1] * k)
        self.cache = {}

    def sprite(self, wt3=0, wt4=0, wp=0, ws=0, wb=0):
        w = dict(zip(self.ORDER, (wt3, wt4, wp, ws, wb)))
        key = tuple(round(w[o], 2) for o in self.ORDER)
        if key not in self.cache:
            mix = self.final['base'].copy()
            for o in self.ORDER:
                if w[o] > 0:
                    kk = (w[o] * self.masks[o])[..., None]
                    mix = mix * (1 - kk) + self.final[o] * kk
            self.cache[key] = Sprite(resize_pm(mix, self.size), None, foot=self.foot)
        return self.cache[key]


def read_weights(i):
    """Reading segment, tick i of the 100-tick reading timeline -> (page, smile(head), blink)."""
    wb = 1.0 if any(a <= i < b for a, b in ((16, 19), (32, 35), (60, 63))) else 0.0
    wp = 1.0 if 44 <= i <= 52 else 0.0                    # hard cuts only: no cross-fade on or near the face
    ws = 1.0 if 77 <= i <= 88 else 0.0
    return wp, ws, wb


DOWN_TICKS = 16
READ_TICKS = 88
READ_OFFSET = 4                  # reading tick j uses read_weights(j + READ_OFFSET)


def down_sequence():
    """Sit-down as (nodeA, nodeB, w) per 70 ms tick; w=0 is a pure key pose, otherwise a short cross-fade."""
    def fade(a, b, ws): return [(a, b, w) for w in ws]
    def hold(a, n=2): return [(a, a, 0)] * n
    seq = [('stand', 'stand', 0)]
    seq += fade('stand', 'T1', (0.33, 0.67)) + hold('T1') + fade('T1', 'T2', (0.5,)) + hold('T2')
    seq += fade('T2', 'T3', (0.33, 0.67)) + hold('T3') + fade('T3', 'T4', (0.5,)) + hold('T4') + fade('T4', 'S1', (0.5,))
    assert len(seq) == DOWN_TICKS
    return seq


def blend(a_img, b_img, w):
    """cross-fade two RGBA images in premultiplied space: (1-w)*a + w*b."""
    pa, pb = premult(np.asarray(a_img, dtype=np.float32)), premult(np.asarray(b_img, dtype=np.float32))
    return unpremult((1 - w) * pa + w * pb)


def magnitude(p):
    return abs(p[4]) * 4 + abs(p[3]) + abs(p[1] - 1) * 400 + abs(p[2])


REST = (1, 1, 0, 0, 0)
SIZE_LIMIT = 4_000_000


class Item:
    """One displayed frame: sprite, params (sx, sy, dx, dy, rot), blink flag, duration in ms, label."""
    __slots__ = ('spr', 'p', 'blink', 'ms', 'label')

    def __init__(self, spr, p=REST, blink=False, ms=FRAME_MS, label=''):
        self.spr, self.p, self.blink, self.ms, self.label = spr, tuple(p), blink, ms, label

    def key(self):
        return (id(self.spr), tuple(round(float(v), 3) for v in self.p), bool(self.blink))


def tick_items(spr, n, f, bl, step=1, label=''):
    return [Item(spr, f(i), i in bl, FRAME_MS * step, f'{label}{i}') for i in range(0, n, step)]


def save_webp(frames, durs, target, quality, limit=SIZE_LIMIT):
    q = quality
    while True:
        frames[0].save(target, save_all=True, append_images=frames[1:], duration=durs, loop=0,
                       lossless=False, quality=q, alpha_quality=100, method=3, exact=True)
        if target.stat().st_size <= limit or q <= 50:
            return q
        q -= 5


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sheet', default='v5', help='source sheet version: sheet-A-<ver>.png / sheet-B-<ver>.png')
    ap.add_argument('--raw', type=Path, default=RAW)
    ap.add_argument('--out', type=Path, default=OUT)
    ap.add_argument('--quality', type=int, default=75)
    ap.add_argument('--preview', type=Path, default=PREVIEW)
    a = ap.parse_args()
    (a.out / 'assets').mkdir(parents=True, exist_ok=True)
    global SIT_DX

    def read_png(name):
        return np.asarray(Image.open(a.raw / name).convert('RGB'))
    A = read_png(f'sheet-A-{a.sheet}.png'); B = read_png(f'sheet-B-{a.sheet}.png')
    assert A.shape == (1024, 1536, 3) and B.shape == A.shape

    # ---- 1. cut, key, blink composite (sheet A / B)
    raw_sprites = {}
    for name, idx in CELLS.items():
        r, c = divmod(idx, 3)
        sl = (slice(r * CELL, (r + 1) * CELL), slice(c * CELL, (c + 1) * CELL))
        ka = drop_specks(key_green(A[sl]))
        mix = None
        if name in BLINKABLE:
            kb = key_green(B[sl])
            m = eye_mask(A[sl], B[sl], ka[..., 3] / 255.0)[..., None]
            mix = ka.copy()
            mix[..., :3] = ka[..., :3] * (1 - m) + kb[..., :3] * m   # alpha stays A's
        raw_sprites[name] = (ka, mix)

    # ---- 2. uniform scale (idle figure -> TARGET_H), premultiplied sprites with foot anchors
    ib0 = bbox(to_img(raw_sprites['idle'][0]))
    scale = TARGET_H / (ib0[3] - ib0[1])
    sz = (round(CELL * scale), round(CELL * scale))
    sprites = {}
    for name, (ka, mix) in raw_sprites.items():
        sprites[name] = Sprite(resize_pm(premult(ka), sz), None if mix is None else resize_pm(premult(mix), sz))
    idle = sprites['idle']
    nat = lambda spr: spr.head_x() - spr.foot[0] + spr.xfix      # head x relative to the sprite's anchor
    for nm in ('thinking', 'working', 'notification', 'attention'):   # same head x as idle: no sideways jump when cutting
        sprites[nm].xfix = nat(idle) - (sprites[nm].head_x() - sprites[nm].foot[0])
        print(f'  head-x fix {nm}: {sprites[nm].xfix:+.1f}px')

    # new pose sprites: foot x = head x, foot y = ground (bottom row), so a per-frame dx puts the head on a smooth path
    def six(name):
        return cut6(read_png(name))
    def node(cell, rel=1.0):
        s2 = (round(CELL * scale * rel),) * 2
        spr = Sprite(resize_pm(premult(cell), s2), None)
        spr.foot = (spr.head_x(), spr.foot[1])
        return spr
    T2c, Zc, Wc = (six(f'sheet-{x}-v5.png') for x in ('T2', 'Z', 'W'))
    T2 = [node(c, SIT_SCALE) for c in T2c]
    Z = [node(c) for c in Zc]
    W = [node(c) for c in Wc]

    rs = ReadSprites(read_png('sheet-S-v5.png'), read_png('sheet-T-v5.png'), sz, sz[0] / CELL)
    sit_ref = rs.sprite()
    sbx, sf = sit_ref.box, sit_ref.foot
    sit_half = max(sf[0] - sbx[0], sbx[2] - sf[0]) + 4
    SIT_DX = round(2 * SIT_SHIFT * (sit_half + MARGIN) / (1 - 2 * SIT_SHIFT))
    print('sit half-width', round(sit_half), 'SIT_DX', SIT_DX)

    def path(nodes, h0, h1):
        """per-node dx so the heads of `nodes` move linearly from head offset h0 to h1 (hard-cut key poses)."""
        n = len(nodes)
        return [h0 + (h1 - h0) * i / (n - 1) - nat(s) for i, s in enumerate(nodes)]

    # ---- 3. frame lists (items) for every animation
    anims = {}
    K = [node(c) for c in cut6(read_png('sheet-K-v5.png'))]
    C = [node(c) for c in cut6(read_png('sheet-C-v5.png'))]
    D = [node(c, SIT_SCALE) for c in cut6(read_png('sheet-D-v5.png'))]

    def feet_x(spr):
        al = np.asarray(spr.planes['o'][3]); y1 = int(spr.foot[1]); k = spr.size[0] / CELL
        sub = al[max(0, y1 - int(25 * k)):y1 + 1]
        return float((sub.sum(axis=0) * np.arange(sub.shape[1])).sum() / max(sub.sum(), 1))
    feet_rel = lambda spr: feet_x(spr) - spr.foot[0] + spr.xfix
    idle_feet = feet_rel(idle)
    planted = lambda spr: idle_feet - feet_rel(spr)            # dx that keeps the feet exactly where idle's feet are

    def pose(spr, ms, label, sy=1.0, sx=1.0):
        return Item(spr, (sx, sy, planted(spr), 0, 0), False, ms, label)

    # 3a. tick-based animations from anim_spec
    for an in ('idle', 'notification', 'attention', 'sleeping', 'idle_hop'):
        n, f, bl = anim_spec(an)
        spr = sprites[SPRITE_OF[an]]
        its = tick_items(spr, n, f, bl, step=2 if n >= 100 else 1)
        if an in IDLE_ANIMS:                                   # mini-animations end exactly on the idle rest pose
            its.append(Item(spr, REST, False, FRAME_MS, 'rest'))
        anims[an] = its

    # 3a'. hand-drawn mini-animations (hard cuts, feet planted on idle's feet)
    # stretch: idle -> K1 -> K2 (hold with two small up-stretches = effort) -> K3 -> K2 -> K1 -> idle  (3.1 s)
    anims['idle_stretch'] = [pose(idle, 100, 'stand'), pose(K[0], 200, 'K1'),
                             pose(K[1], 325, 'K2'), pose(K[1], 325, 'K2 up', 1.014), pose(K[1], 325, 'K2'), pose(K[1], 325, 'K2 up', 1.014),
                             pose(K[2], 450, 'K3'), pose(K[2], 450, 'K3 up', 1.012),
                             pose(K[1], 300, 'K2 back'), pose(K[0], 200, 'K1 back'), pose(idle, 100, 'stand')]
    # look around, hand over the eyes: idle -> K4 -> K5 (left) -> K4 -> K6 (right) -> K4 -> idle  (3.9 s)
    anims['idle_look'] = [pose(idle, 100, 'stand'), pose(K[3], 300, 'K4'), pose(K[4], 1400, 'K5 left'), pose(K[3], 300, 'K4'),
                          pose(K[5], 1400, 'K6 right'), pose(K[3], 300, 'K4 back'), pose(idle, 100, 'stand')]
    # head tilt left, finger on cheek, wink, hands to cheek, no vertical movement  (4.3 s)
    anims['idle_tilt'] = [pose(idle, 100, 'stand'), pose(C[0], 150, 'C1'), pose(C[1], 900, 'C2'), pose(C[2], 800, 'C3'),
                          pose(C[3], 600, 'C4 wink'), pose(C[2], 300, 'C3 back'), pose(C[5], 900, 'C6'), pose(C[4], 250, 'C5'),
                          pose(C[0], 200, 'C1 back'), pose(idle, 100, 'stand')]
    # head pat: the hand rests on her head and she sways her head left / right under it, then hands to cheeks  (7.3 s)
    Hc = cut6(read_png('sheet-H-v6.png'))
    top_fade = np.clip(np.arange(CELL, dtype=np.float32) / 18.0, 0, 1)
    for c in Hc:                                               # the wrist fades out at the cell top instead of a hard edge
        c[..., 3] *= (top_fade * top_fade * (3 - 2 * top_fade))[:, None]
    P = [node(c, rel) for c, rel in zip(Hc, PAT_SCALE)]
    anims['idle_pat'] = [pose(idle, 150, 'stand'), pose(P[0], 700, 'H1 hand on'),
                         pose(P[1], 900, 'H2 left'), pose(P[3], 450, 'H4 mid'), pose(P[2], 900, 'H3 right'), pose(P[3], 450, 'H4 mid'),
                         pose(P[1], 900, 'H2 left'), pose(P[3], 500, 'H4 mid'),
                         pose(P[4], 900, 'H5 cheeks'), pose(P[5], 1300, 'H6 shy'), pose(idle, 150, 'stand')]

    # 3b. idle_read: sit down (D series, feet planted until D2, then heads on a smooth path) -> read -> stand up (reverse)
    T4s, S1s = rs.sprite(0, 1), rs.sprite()
    nodes = [idle, T2[0], T2[1], D[0], D[1], D[2], D[3], D[4], D[5]]
    labels = ['stand', 'T2-1', 'T2-2', 'D1', 'D2', 'D3', 'D4', 'D5', 'D6']
    dur_down = [90, 100, 130, 110, 100, 110, 110, 110, 130]
    dxs = [planted(s) for s in nodes[:5]]
    h_start, h_end = dxs[4], nat(T4s) + SIT_DX                  # head offset of D2 as placed -> head of T4 at the sitting spot
    for j in range(1, 5):
        dxs.append(h_start + (h_end - h_start) * j / 4)
    down = [Item(s, (1, 1, dx, 0, 0), False, ms, lb) for s, dx, ms, lb in zip(nodes, dxs, dur_down, labels)]
    down.append(Item(T4s, (1, 1, SIT_DX, 0, 0), False, 110, 'T4'))
    n_read, f_read, _ = anim_spec('idle_read')
    reading, j = [], 0
    while j < READ_TICKS:
        w = read_weights(j + READ_OFFSET)
        ln = 2 if (j + 1 < READ_TICKS and read_weights(j + 1 + READ_OFFSET) == w) else 1
        reading.append(Item(rs.sprite(0, 0, *w), f_read(DOWN_TICKS + j), False, ln * FRAME_MS,
                            'read' + ('' if w == (0, 0, 0) else f' p{w[0]:g} h{w[1]:g} b{w[2]:g}')))
        j += ln
    anims['idle_read'] = down + reading + [Item(i.spr, i.p, i.blink, i.ms, i.label + ' up') for i in reversed(down)]

    # 3c. sleep sequence for clawd's full mode
    A6 = sprites['sleeping']
    sq = (1.03, 0.92)                                          # one "knees bend" frame: squash of Z2 about its feet
    nodes_y = [idle, Z[0], Z[1], Z[1], Z[2], Z[3], A6]
    dxs = path(nodes_y, nat(idle), nat(A6))
    prm = [(1, 1, d, 0, 0) for d in dxs]; prm[3] = (sq[0], sq[1], dxs[3], 0, 0)
    ms_y = [90, 800, 130, 90, 130, 200, 150]
    lab_y = ['stand', 'Z1 yawn', 'Z2', 'Z2 squash', 'Z3', 'Z4', 'sleeping']
    anims['yawning'] = [Item(s, p, False, ms, lb) for s, p, ms, lb in zip(nodes_y, prm, ms_y, lab_y)]
    # waking (2.5 s): eyes open and stay, rub eyes (longer), rise in two small steps, stand, idle
    nodes_w = [A6, Z[4], Z[5], Z[1], Z[1], Z[1], idle]
    dxs = path(nodes_w, nat(A6), nat(idle))
    ys = [(1, 1), (1, 1), (1, 1), (1.02, 0.92), (1.01, 0.96), (1, 1), (1, 1)]
    prm = [(sx_, sy_, d, 0, 0) for (sx_, sy_), d in zip(ys, dxs)]
    ms_w = [200, 700, 900, 150, 120, 350, 120]
    lab_w = ['sleeping', 'Z5 awake', 'Z6 rub eyes', 'Z2 squash', 'Z2 half', 'Z2', 'stand']
    anims['waking'] = [Item(s, p, False, ms, lb) for s, p, ms, lb in zip(nodes_w, prm, ms_w, lab_w)]

    # 3d/3e. thinking and working pieces: idle -> poses -> loop -> back. Used by the state loops and the short menu clips.
    A2, A3 = sprites['thinking'], sprites['working']
    w6_dx = nat(A3) - nat(W[5])

    def make_think(steps, blink_steps, back=True):
        nodes_t = [idle, W[0], W[1], A2]
        dxs = path(nodes_t, nat(idle), nat(A2))
        pre = [Item(s, (1, 1, d, 0, 0), False, ms, lb) for s, d, ms, lb in zip(nodes_t[:3], dxs[:3], (90, 110, 130), ('stand', 'W1', 'W2'))]
        blink_t = set()
        for s0 in blink_steps:
            blink_t.update((s0, s0 + 1))
        hold = []
        for s in range(steps):
            t = s / steps
            p = 0.5 - 0.5 * math.cos(2 * math.pi * 3 * t)
            hold.append(Item(A2, (1 - 0.004 * p, 1 + 0.015 * p, 0, 0, 3.0 * math.sin(2 * math.pi * t)), s in blink_t, 140, f'think{s}'))
        hold.append(Item(A2, REST, False, 140, 'think rest'))
        post = [Item(i.spr, i.p, False, i.ms, i.label + ' back') for i in reversed(pre[1:])] + [Item(idle, REST, False, 90, 'stand')]
        return pre + hold + post

    def make_work(steps, step_ms, blink_steps, w6_at=None, w6_ms=1500, w6_end=False):
        nodes_k = [idle, W[2], W[3], W[4], A3]
        dxs = path(nodes_k, nat(idle), nat(A3))
        pre = [Item(s, (1, 1, d, 0, 0), False, ms, lb) for s, d, ms, lb in zip(nodes_k[:4], dxs[:4], (90, 120, 120, 130), ('stand', 'W3', 'W4', 'W5'))]
        hold, s = [], 0
        skip = max(1, round(w6_ms / step_ms))
        while s < steps:
            if w6_at is not None and s == w6_at:                 # head-up smile (hard cut in / out)
                hold.append(Item(W[5], (1, 1, w6_dx, 0, 0), False, w6_ms, 'W6 smile')); s += skip; continue
            p = 0.5 - 0.5 * math.cos(2 * math.pi * s / 8)        # 8 steps per breath
            prm = (1 - 0.006 * p, 1 + 0.02 * p, 0, 0, 0)
            if s in blink_steps:
                hold += [Item(A3, prm, True, 140, f'work{s} blink'), Item(A3, prm, False, step_ms - 140, f'work{s}')]
            else:
                hold.append(Item(A3, prm, False, step_ms, f'work{s}'))
            s += 1
        if w6_end:
            hold.append(Item(W[5], (1, 1, w6_dx, 0, 0), False, w6_ms, 'W6 smile'))
        else:
            hold.append(Item(A3, REST, False, step_ms, 'work rest'))
        post = [Item(i.spr, i.p, False, i.ms, i.label + ' back') for i in reversed(pre[1:])] + [Item(idle, REST, False, 90, 'stand')]
        return pre + hold + post

    anims['thinking'] = make_think(80, (14, 38, 52, 57, 70))                       # ~12 s
    anims['working'] = make_work(108, 420, {5, 11, 17, 19, 25, 31, 37, 43, 48, 60, 66, 72, 74, 80, 86, 92, 98, 104}, 54, 1680)   # ~47 s
    anims['idle_think'] = make_think(23, (6, 15))                                   # ~4 s, menu clip
    anims['idle_work'] = make_work(12, 420, {3, 9}, None, 1200, True)               # ~7.6 s, menu clip

    # ---- 3f. canvas extent from every frame of every animation
    ext = [0, 0, 0, 0]   # l, r, up, down relative to anchor (0,0)
    seen = set()
    for an, its in anims.items():
        for it in its:
            k_ = it.key()
            if k_ in seen: continue
            seen.add(k_)
            x, y = it.spr.map_points(it.p, (0, 0))
            ext = [max(ext[0], -x.min()), max(ext[1], x.max()), max(ext[2], -y.min()), max(ext[3], y.max())]
    half = math.ceil(max(ext[0], ext[1])) + MARGIN
    CW, CH = half * 2, math.ceil(ext[2]) + MARGIN + math.ceil(ext[3]) + MARGIN
    anchor = (half, math.ceil(ext[2]) + MARGIN)
    canvas = (CW, CH)
    print('canvas', canvas, 'anchor', anchor, 'scale', round(scale, 3))

    # ---- 4. render + encode (consecutive identical frames are merged)
    cache, info, boxes, frames_of = {}, {}, {}, {}
    for an, its in anims.items():
        frames, durs, labels_, merged = [], [], [], []
        for it in its:
            k_ = it.key()
            if k_ not in cache:
                cache[k_] = it.spr.render(it.p, canvas, anchor, blink=it.blink)
            img = cache[k_]
            if frames and frames[-1] is img:
                durs[-1] += it.ms
            else:
                frames.append(img); durs.append(it.ms); labels_.append(it.label); merged.append(it)
        frames_of[an] = (frames, durs, labels_, merged)
        boxes[an] = (lambda bs: (min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs)))(
            [bbox(f) for f in frames])
        target = a.out / 'assets' / f'{an}.webp'
        q = save_webp(frames, durs, target, a.quality)
        info[an] = (len(frames), sum(durs), target.stat().st_size)
        print(f'{an}: {len(frames)} frames, {sum(durs)} ms, {target.stat().st_size / 1e6:.2f} MB (q{q}), box {boxes[an]}')

    # ---- 4b. smoothness report
    def pm_arr(img): return premult(np.asarray(img, dtype=np.float32))
    idle_f0 = frames_of['idle'][0][0]
    mad = lambda x, y: float(np.abs(pm_arr(x) - pm_arr(y)).mean())
    print('--- first / last frame mean abs diff vs idle frame 0 (premultiplied RGBA, 0-255):')
    jumps = []
    for an in anims:
        fr = frames_of[an][0]
        pairs = [(mad(f0, f1), i, (i + 1) % len(fr)) for i, (f0, f1) in enumerate(zip(fr, fr[1:] + fr[:1]))]
        pairs.sort(reverse=True)
        jumps += [(v, an, i0, labels_i) for v, i0, labels_i in pairs[:2]]
        print(f'  {an:13s} first {mad(fr[0], idle_f0):6.2f}  last {mad(fr[-1], idle_f0):6.2f}   '
              f'max step {pairs[0][0]:5.2f} ({frames_of[an][2][pairs[0][1]]} -> {frames_of[an][2][pairs[0][2]]})')
    print('  seams: yawning last vs sleeping first %.2f | sleeping first vs waking first %.2f | waking last vs idle first %.2f'
          % (mad(frames_of['yawning'][0][-1], frames_of['sleeping'][0][0]), mad(frames_of['sleeping'][0][0], frames_of['waking'][0][0]),
             mad(frames_of['waking'][0][-1], idle_f0)))
    print('  loop seams (last -> first): thinking %.2f, working %.2f' % (
        mad(frames_of['thinking'][0][-1], frames_of['thinking'][0][0]), mad(frames_of['working'][0][-1], frames_of['working'][0][0])))
    jumps.sort(reverse=True)
    print('--- largest single steps:', [(an, round(float(v), 1), frames_of[an][2][i0]) for v, an, i0, _ in jumps[:10]])

    # ---- 5. theme.json
    ib = bbox(frames_of['idle'][0][0])
    cw, ch = ib[2] - ib[0], ib[3] - ib[1]
    ub = (min(b[0] for b in boxes.values()), min(b[1] for b in boxes.values()),
          max(b[2] for b in boxes.values()), max(b[3] for b in boxes.values()))
    hit = {'x': ub[0], 'y': ub[1], 'w': ub[2] - ub[0], 'h': ub[3] - ub[1]}
    d = lambda n: info[n][1]
    click_files = ['idle_read', 'idle_tilt', 'idle_pat','idle_look', 'idle_stretch', 'idle_hop']
    click = {'file': 'idle_hop.webp', 'duration': d('idle_hop'),
             'files': [f'{n}.webp' for n in click_files],
             'durations': {f'{n}.webp': d(n) for n in click_files}}
    menu = [('看书', 'idle_read'), ('工作', 'idle_work'), ('思考', 'idle_think'), ('歪头', 'idle_tilt'), ('摸头', 'idle_pat'), ('张望', 'idle_look'), ('小跳', 'idle_hop'),
            ('伸懒腰', 'idle_stretch'), ('欢呼', 'attention'), ('打招呼', 'notification'), ('打哈欠', 'yawning')]
    theme = {
        'schemaVersion': 1,
        'name': '一之濑帆波 (Honami)',
        'author': '同人图（Q 版一之濑帆波设定图），本主题仅为格式转换与程序动作',
        'version': '0.4.0',
        'description': '同人图，个人本地使用，不分发。',
        'preview': 'idle.webp',
        'viewBox': {'x': 0, 'y': 0, 'width': CW, 'height': CH},
        'layout': {
            'contentBox': {'x': ib[0], 'y': ib[1], 'width': cw, 'height': ch},
            'centerX': round((ib[0] + ib[2]) / 2, 1), 'baselineY': ib[3],
            'visibleHeightRatio': 0.78, 'baselineBottomRatio': 0.05,
        },
        'eyeTracking': {'enabled': False, 'states': []},
        'states': {
            'idle': ['idle.webp'], 'thinking': ['thinking.webp'], 'working': ['working.webp'],
            'attention': ['attention.webp'], 'notification': ['notification.webp'],
            'error': {'fallbackTo': 'notification'},
            'sweeping': {'fallbackTo': 'working'}, 'carrying': {'fallbackTo': 'working'},
            # full sleep sequence: idle -> yawning -> dozing -> (deep) collapsing -> sleeping; mouse move -> waking -> idle
            'yawning': ['yawning.webp'], 'dozing': ['sleeping.webp'], 'collapsing': ['sleeping.webp'],
            'sleeping': ['sleeping.webp'], 'waking': ['waking.webp'],
        },
        'sleepSequence': {'mode': 'full'},
        # idle_read listed twice = twice the chance in clawd's uniform random pick
        'idleAnimations': [{'file': f'{n}.webp', 'duration': d(n)} for n in IDLE_ANIMS + ['idle_read']],
        'timings': {
            'mouseIdleTimeout': 25000, 'mouseSleepTimeout': MOUSE_SLEEP_MS, 'deepSleepTimeout': 3000,
            'yawnDuration': d('yawning'), 'wakeDuration': d('waking'), 'collapseDuration': 100,
            'minDisplay': {'notification': d('notification'), 'error': d('notification'), 'attention': d('attention')},
            'autoReturn': {'notification': d('notification'), 'error': d('notification'), 'attention': d('attention')},
        },
        'hitBoxes': {'default': hit},
        'reactions': {
            'clickLeft': click, 'clickRight': click,
            'double': {'files': ['attention.webp'], 'duration': d('attention')},
            # menu-only clips: listed here so clawd counts them as theme assets (the right-click menu can then play them)
            'menuOnly': {'files': ['idle_work.webp', 'idle_think.webp']},
        },
        # read by the locally patched clawd (right-click -> "做动作")
        'actionMenu': [{'label': lb, 'file': f'{fn}.webp', 'duration': d(fn)} for lb, fn in menu],
        'miniMode': {'supported': False},
    }
    (a.out / 'theme.json').write_text(json.dumps(theme, ensure_ascii=False, indent=2), encoding='utf-8')

    # ---- 6. previews
    k = 0.55
    tw, th = round(CW * k), round(CH * k)
    tile = 20
    chk = Image.new('RGB', (CW, CH))
    dr = ImageDraw.Draw(chk)
    for y in range(0, CH, tile):
        for x in range(0, CW, tile):
            dr.rectangle([x, y, x + tile - 1, y + tile - 1],
                         fill=(205, 205, 205) if (x // tile + y // tile) % 2 else (160, 160, 160))

    def tile_img(img, text, kk=k):
        bg = chk.copy(); bg.paste(img, (0, 0), img)
        bg = bg.resize((round(CW * kk), round(CH * kk)), Image.LANCZOS)
        ImageDraw.Draw(bg).text((4, 4), text, fill=(0, 0, 0))
        return bg

    def pick(an, label_prefix):
        fr, _, lbs, _ = frames_of[an]
        for i, lb in enumerate(lbs):
            if lb == label_prefix:
                return fr[i], lb
        for i, lb in enumerate(lbs):
            if lb.startswith(label_prefix):
                return fr[i], lb
        raise KeyError((an, label_prefix))

    order = ['idle', 'thinking', 'working', 'notification', 'attention', 'sleeping', 'idle_hop']
    rows_a = (len(order) + 1) // 2
    trans_rows = [
        [('idle_stretch', 'stand'), ('idle_stretch', 'K1'), ('idle_stretch', 'K2'), ('idle_stretch', 'K2 up'), ('idle_stretch', 'K3'), ('idle_stretch', 'K1 back')],
        [('idle_look', 'stand'), ('idle_look', 'K4'), ('idle_look', 'K5'), ('idle_look', 'K4 back'), ('idle_look', 'K6'), ('idle_look', 'stand')],
        [('idle_tilt', 'C1'), ('idle_tilt', 'C2'), ('idle_tilt', 'C3'), ('idle_tilt', 'C4'), ('idle_tilt', 'C6'), ('idle_tilt', 'C5')],
        [('idle_pat', 'H1'), ('idle_pat', 'H2'), ('idle_pat', 'H4'), ('idle_pat', 'H3'), ('idle_pat', 'H5'), ('idle_pat', 'H6')],
        [('idle_read', 'stand'), ('idle_read', 'T2-1'), ('idle_read', 'T2-2'), ('idle_read', 'D1'), ('idle_read', 'D2'), ('idle_read', 'D3')],
        [('idle_read', 'D4'), ('idle_read', 'D5'), ('idle_read', 'D6'), ('idle_read', 'T4'), ('idle_read', 'read p0 h0 b1'), ('idle_read', 'read p1 h0 b0')],
        [('yawning', 'stand'), ('yawning', 'Z1'), ('yawning', 'Z2'), ('yawning', 'Z3'), ('yawning', 'Z4'), ('yawning', 'sleeping')],
        [('waking', 'sleeping'), ('waking', 'Z5'), ('waking', 'Z6'), ('waking', 'Z2 squash'), ('waking', 'Z2 half'), ('waking', 'stand')],
        [('idle_work', 'stand'), ('idle_work', 'W3'), ('idle_work', 'W4'), ('idle_work', 'W5'), ('idle_work', 'work0'), ('idle_work', 'W6')],
        [('idle_think', 'stand'), ('idle_think', 'W1'), ('idle_think', 'W2'), ('idle_think', 'think3'), ('idle_think', 'think6'), ('idle_think', 'W1 back')],
    ]
    sheet = Image.new('RGB', (tw * 6, th * (rows_a + len(trans_rows))), (255, 255, 255))
    for j_, an in enumerate(order):
        its = anims[an]
        mags = [magnitude(i.p) for i in its]
        kmax = max(range(len(its)), key=lambda i: mags[i])
        bi = next((i for i, it in enumerate(its) if it.blink), len(its) // 2)
        for c, i in enumerate([0, kmax, bi]):
            img = cache[its[i].key()]
            sheet.paste(tile_img(img, f'{an} #{i}' + (' blink' if its[i].blink else '')), (((j_ % 2) * 3 + c) * tw, (j_ // 2) * th))
    for r_, row in enumerate(trans_rows):
        for c, (an, lb) in enumerate(row):
            img, lb2 = pick(an, lb)
            sheet.paste(tile_img(img, f'{an}: {lb2}'), (c * tw, (rows_a + r_) * th))
    sheet.save(a.preview)

    def strip(entries, path_, cols=12, ks=0.26):
        """entries: (img, text) -> grid of thumbnails."""
        sw, sh_ = round(CW * ks), round(CH * ks)
        rws = (len(entries) + cols - 1) // cols
        im = Image.new('RGB', (cols * sw, rws * sh_), (255, 255, 255))
        for q_, (img, text) in enumerate(entries):
            im.paste(tile_img(img, text, ks), ((q_ % cols) * sw, (q_ // cols) * sh_))
        im.save(path_)

    def entries_of(an, idxs=None, tag=None):
        fr, du, lb, _ = frames_of[an]
        idxs = range(len(fr)) if idxs is None else idxs
        return [(fr[i], f'{tag or an[:5]}{i} {du[i]}ms') for i in idxs]
    pdir = a.preview.parent
    strip(entries_of('idle_read'), pdir / 'honami-read-strip.png', cols=10, ks=0.3)
    strip(entries_of('yawning', tag='yawn') + entries_of('waking', tag='wake'), pdir / 'honami-sleep-strip.png', cols=7, ks=0.34)
    nt, nw = len(frames_of['thinking'][0]), len(frames_of['working'][0])
    w6 = next(i for i, lb in enumerate(frames_of['working'][2]) if lb.startswith('W6'))
    strip(entries_of('thinking', list(range(0, 8)) + list(range(nt - 6, nt)), 'think')
          + entries_of('working', list(range(0, 10)) + list(range(w6 - 2, w6 + 3)) + list(range(nw - 6, nw)), 'work'),
          pdir / 'honami-work-strip.png', cols=8, ks=0.3)
    print('content box', ib, 'hit', hit, 'preview ->', a.preview)


if __name__ == '__main__':
    main()
