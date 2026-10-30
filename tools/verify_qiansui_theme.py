"""Decode every WebP in the theme, print a table, and render a preview sheet."""
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageSequence

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / 'qiansui'
SHEET = HERE.parent / 'qiansui-preview.png'
STATES = [('idle', 'idle / sleeping(fallback)'), ('idle2', 'idleAnimation: idle2'), ('greeting', 'idleAnimation+click: greeting'),
          ('thinking', 'thinking'), ('working', 'working'), ('attention', 'attention'), ('notification', 'notification / error(fallback)')]
TW, TH = 216, 289

def checker(w, h, s=12):
    im = Image.new('RGBA', (w, h), (235, 235, 235, 255)); d = ImageDraw.Draw(im)
    for y in range(0, h, s):
        for x in range(0, w, s):
            if (x // s + y // s) % 2: d.rectangle([x, y, x + s - 1, y + s - 1], fill=(190, 190, 190, 255))
    return im

font = ImageFont.truetype(r'C:\Windows\Fonts\msyh.ttc', 14)
sheet = Image.new('RGBA', (TW * 3 + 40, (TH + 30) * len(STATES) + 10), (255, 255, 255, 255))
d = ImageDraw.Draw(sheet)
print('file | frames | size | alpha | total ms | KB')
for row, (name, label) in enumerate(STATES):
    p = OUT / 'assets' / f'{name}.webp'
    with Image.open(p) as im:
        frames = []; total = 0
        for fr in ImageSequence.Iterator(im):
            total += fr.info.get('duration', 0); frames.append(fr.convert('RGBA'))
        amin = min(f.getchannel('A').getextrema()[0] for f in frames)
        amax = max(f.getchannel('A').getextrema()[1] for f in frames)
        print(f'{p.name} | {len(frames)} | {im.size} | min{amin}/max{amax} | {total} | {p.stat().st_size//1024}')
    y0 = row * (TH + 30) + 5
    d.text((10, y0), f'{label}  ({len(frames)}f, {total}ms)', fill=(0, 0, 0, 255), font=font)
    for k, idx in enumerate([0, len(frames) // 2, len(frames) - 1]):
        t = checker(TW, TH); f = frames[idx].resize((TW, TH), Image.LANCZOS)
        t.alpha_composite(f); sheet.paste(t, (10 + k * (TW + 10), y0 + 24))
sheet.convert('RGB').save(SHEET)
print('sheet', SHEET)
