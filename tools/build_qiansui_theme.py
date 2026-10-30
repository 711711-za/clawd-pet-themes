"""Build the clawd-on-desk 'qiansui' theme from the QianSui1 PNG frame folders.
Read-only on the source; writes only into the output dir.
Usage: python build_qiansui_theme.py [--src QianSui1_dir] [--out theme_dir] [--quality 85]
"""
import argparse, json, shutil
from pathlib import Path
from PIL import Image

HERE = Path(__file__).resolve().parent
DEFAULT_SRC = HERE.parent.parent / 'QianSui1'
DEFAULT_OUT = HERE.parent / 'qiansui'
FRAME_MS = 70  # same as maid-widget prepare-local-characters.py
# name -> (first, last, ms): slow down a frame range so it stays on screen longer.
# notification: sign text is fully written from ~frame 75; hold it at half speed.
SLOW = {'notification': (75, 127, 140)}
MOUSE_SLEEP_MS = 600000  # no mouse for 10 min -> sleeping (fantasy loop), same as 结灯

# output name -> source folder
ANIMS = {
    'idle': '待机新', 'idle2': '待机2新', 'thinking': '沉思新', 'greeting': '打招呼新',
    'working': '送信新', 'notification': '提醒新', 'attention': '幻想新',
}


CANVAS = (432, 578)  # source frames are 432x577 or 432x578; bottom-align onto 432x578


def fit(im):
    if im.size == CANVAS:
        return im
    assert im.size[0] == CANVAS[0] and 0 <= CANVAS[1] - im.size[1] <= 2, im.size
    out = Image.new('RGBA', CANVAS, (0, 0, 0, 0))
    out.paste(im, (0, CANVAS[1] - im.size[1]))
    return out


def load(folder):
    files = sorted(folder.glob('f_*.png'))
    if not files:
        raise SystemExit(f'no frames in {folder}')
    frames = []
    for f in files:
        with Image.open(f) as im:
            frames.append(fit(im.convert('RGBA')))
    return frames


def union_bbox(frames):
    box = None
    for fr in frames:
        b = fr.getchannel('A').point(lambda v: 255 if v > 16 else 0).getbbox()
        if b:
            box = b if box is None else (min(box[0], b[0]), min(box[1], b[1]), max(box[2], b[2]), max(box[3], b[3]))
    return box


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', type=Path, default=DEFAULT_SRC)
    ap.add_argument('--out', type=Path, default=DEFAULT_OUT)
    ap.add_argument('--quality', type=int, default=85)
    a = ap.parse_args()
    img = a.src / 'image'
    (a.out / 'assets').mkdir(parents=True, exist_ok=True)

    info, boxes, size = {}, {}, None
    for name, folder in ANIMS.items():
        frames = load(img / folder)
        size = size or frames[0].size
        assert all(f.size == size for f in frames), name
        boxes[name] = union_bbox(frames)
        target = a.out / 'assets' / f'{name}.webp'
        durs = [FRAME_MS] * len(frames)
        if name in SLOW:
            lo, hi, ms = SLOW[name]
            durs[lo:hi + 1] = [ms] * (hi + 1 - lo)
        frames[0].save(target, save_all=True, append_images=frames[1:], duration=durs, loop=0,
                       lossless=False, quality=a.quality, alpha_quality=100, method=6, exact=True)
        info[name] = (len(frames), sum(durs), target.stat().st_size)
        print(f'{name}: {len(frames)} frames, {target.stat().st_size/1e6:.2f} MB')

    W, H = size
    bx0 = min(b[0] for b in boxes.values()); by0 = min(b[1] for b in boxes.values())
    bx1 = max(b[2] for b in boxes.values()); by1 = max(b[3] for b in boxes.values())
    # idle pose box (tight) for layout; union box for hit area
    ib = boxes['idle']
    cw, ch = ib[2] - ib[0], ib[3] - ib[1]
    vhr = 0.78  # hand-tuned after install (formula 0.36*sqrt(ch/cw) looked too small)
    hit = {'x': bx0, 'y': by0, 'w': bx1 - bx0, 'h': by1 - by0}
    d = lambda n: info[n][1]
    theme = {
        'schemaVersion': 1,
        'name': '千岁 (QianSui)',
        'author': '原作者见 QianSui1 随附的《用前必看！！！.txt》（B站个人作品，MIT 协议），本主题仅为格式转换',
        'version': '0.1.0',
        'description': '个人本地使用。千岁桌宠 PNG 帧序列转换为 clawd-on-desk 主题，素材版权归原作者。',
        'preview': 'idle.webp',
        'viewBox': {'x': 0, 'y': 0, 'width': W, 'height': H},
        'layout': {
            'contentBox': {'x': ib[0], 'y': ib[1], 'width': cw, 'height': ch},
            'centerX': round((ib[0] + ib[2]) / 2, 1), 'baselineY': ib[3],
            'visibleHeightRatio': vhr, 'baselineBottomRatio': 0.05,
        },
        'eyeTracking': {'enabled': False, 'states': []},
        'states': {
            'idle': ['idle.webp'],
            'thinking': ['thinking.webp'],
            # asset names follow the source folders, not clawd states:
            # working state = 待机2 (maid), attention (task done) = 送信, sleeping = 幻想
            'working': ['idle2.webp'],
            'attention': ['working.webp'],
            'notification': ['notification.webp'],
            'error': {'fallbackTo': 'notification'},
            'sweeping': {'fallbackTo': 'working'},
            'carrying': {'fallbackTo': 'working'},
            'sleeping': ['attention.webp'],
        },
        'sleepSequence': {'mode': 'direct'},
        'idleAnimations': [
            {'file': 'idle2.webp', 'duration': d('idle2')},
            {'file': 'greeting.webp', 'duration': d('greeting')},
        ],
        # clawd defaults cut one-shot states at 2.5-5 s; play them through once
        'timings': {
            'mouseIdleTimeout': 60000, 'mouseSleepTimeout': MOUSE_SLEEP_MS,
            'minDisplay': {'notification': d('notification'), 'error': d('notification'),
                           'attention': d('working')},
            'autoReturn': {'notification': d('notification'), 'error': d('notification'),
                           'attention': d('working')},
        },
        'hitBoxes': {'default': hit},
        'reactions': {
            'clickLeft': {'file': 'greeting.webp', 'duration': d('greeting')},
            'clickRight': {'file': 'greeting.webp', 'duration': d('greeting')},
            'double': {'files': ['attention.webp'], 'duration': d('attention')},
        },
        'miniMode': {'supported': False},
    }
    (a.out / 'theme.json').write_text(json.dumps(theme, ensure_ascii=False, indent=2), encoding='utf-8')
    for fn in ['LICENSE', '用前必看！！！.txt']:
        shutil.copy2(a.src / fn, a.out / fn)
    print('content box', ib, 'union box', (bx0, by0, bx1, by1), 'vhr', vhr)

if __name__ == '__main__':
    main()
