"""Build a demo photo set (CC photos + engineered dupes/junk) and optionally upload it to Google Photos.

uv run python scripts/demo_set.py                    # build set 1 into /tmp/jevsort-demo
uv run python scripts/demo_set.py --upload           # build (if needed) and upload via the logged-in Chrome
uv run python scripts/demo_set.py --set 2 --upload   # a second, different set (next page of results)
"""

import argparse
import asyncio
import io
import random
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

OUT = Path("/tmp/jevsort-demo")
QUERIES = {
    "dog": 8, "cat": 5, "pizza": 4, "sushi": 3, "salad": 2, "tropical beach": 8, "city skyline": 6,
    "mountain landscape": 6, "birthday party": 5, "vintage car": 4, "portrait smiling person": 6,
}
UA = {"User-Agent": "jevsort-demo/0.1 (hackathon demo)"}
rng = random.Random(42)


async def fetch_stock(client: httpx.AsyncClient, page: int) -> list[Image.Image]:
    sem = asyncio.Semaphore(6)

    async def one_query(q: str, n: int) -> list[Image.Image]:
        res = await client.get(
            "https://api.openverse.org/v1/images/",
            params={"q": q, "page": page, "page_size": n * 2, "license_type": "all-cc", "mature": "false", "source": "flickr"},
        )
        images = []
        for r in res.json()["results"]:
            if len(images) >= n:
                break
            for url in filter(None, (r["url"], r.get("thumbnail"))):
                try:
                    async with sem:
                        img = await client.get(url, timeout=20)
                    im = Image.open(io.BytesIO(img.content)).convert("RGB")
                    im.thumbnail((1600, 1600))
                    images.append(im)
                    break
                except Exception as e:
                    print(f"  skip {url[:80]}: {e}")
        print(f"{q}: {len(images)}")
        return images

    groups = await asyncio.gather(*(one_query(q, n) for q, n in QUERIES.items()))
    return [im for g in groups for im in g]


def font(size: int):
    for f in ("/System/Library/Fonts/Helvetica.ttc", "/System/Library/Fonts/SFNS.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            pass
    return ImageFont.load_default()


def screenshot(i: int) -> Image.Image:
    dark = rng.random() < 0.4
    bg, fg = ((18, 18, 20), "white") if dark else ((242, 242, 247), "black")
    accent = tuple(rng.randint(30, 230) for _ in range(3))
    im = Image.new("RGB", (1170, 2532), bg)
    d = ImageDraw.Draw(im)
    d.text((60, 40), f"{rng.randint(7, 11)}:{rng.randint(10, 59)}", fill=fg, font=font(48))
    d.text((60, 190), rng.choice(["Messages", "Settings", "Order confirmed", "Boarding pass", "Weather", "Stocks", "Maps", "Music"]), fill=fg, font=font(64))
    layout = i % 4
    if layout == 0:
        for row in range(12):
            y, mine = 360 + row * 170, rng.random() < 0.5
            x0, x1 = (300, 1110) if mine else (60, 870)
            d.rounded_rectangle((x0, y, x1, y + 140), 30, fill=accent if mine else ((58, 58, 60) if dark else "white"))
            d.text((x0 + 40, y + 45), f"message {row + 1} at {rng.randint(1, 12)}pm", fill="white" if mine or dark else "black", font=font(40))
    elif layout == 1:
        for col in range(8):
            h = rng.randint(200, 1400)
            d.rectangle((80 + col * 130, 2000 - h, 170 + col * 130, 2000), fill=accent)
        d.text((80, 2100), f"+{rng.uniform(0.1, 9):.2f}% today", fill=fg, font=font(56))
    elif layout == 2:
        for r in range(4):
            for c in range(3):
                shade = tuple(min(255, max(0, v + rng.randint(-60, 60))) for v in accent)
                d.rounded_rectangle((60 + c * 360, 360 + r * 420, 380 + c * 360, 740 + r * 420), 24, fill=shade)
    else:
        d.rectangle((0, 330, 1170, 1100), fill=accent)
        for row in range(14):
            d.text((60, 1160 + row * 90), f"Setting option {row + 1}" + " ." * rng.randint(3, 12), fill=fg, font=font(40))
    return im


def receipt(i: int) -> Image.Image:
    im = Image.new("RGB", (900, 1500), (70, 60, 50))
    paper = Image.new("RGB", (620, 1300), (250, 248, 240))
    d = ImageDraw.Draw(paper)
    d.text((170, 40), ["CORNER CAFE", "FRESH MART", "HARDWARE CO", "TAXI #481"][i % 4], fill="black", font=font(44))
    total = 0.0
    for row in range(14):
        price = rng.uniform(1, 25)
        total += price
        d.text((40, 150 + row * 60), f"Item {row + 1:02d}", fill="black", font=font(32))
        d.text((460, 150 + row * 60), f"${price:6.2f}", fill="black", font=font(32))
    d.text((40, 1050), f"TOTAL        ${total:7.2f}", fill="black", font=font(40))
    im.paste(paper.rotate(rng.uniform(-6, 6), expand=True, fillcolor=(70, 60, 50)), (120, 80))
    return im


def near_dup(im: Image.Image) -> Image.Image:
    w, h = im.size
    c = im.crop((int(w * 0.02), int(h * 0.02), int(w * 0.98), int(h * 0.98))).resize((w, h))
    return ImageEnhance.Brightness(c).enhance(rng.uniform(0.92, 1.08))


def pocket_shot() -> Image.Image:
    im = Image.effect_noise((800, 1066), 60).convert("RGB")
    im = Image.blend(im, Image.new("RGB", im.size, (60, 40, 30)), 0.8)
    return im.filter(ImageFilter.GaussianBlur(25))


def build(out: Path, page: int, first: int) -> list[Path]:
    out.mkdir(exist_ok=True)
    stock = asyncio.run(_fetch(page))
    photos = list(stock)
    photos += [near_dup(im) for im in rng.sample(stock, 8)]
    photos += [im.filter(ImageFilter.GaussianBlur(rng.uniform(6, 12))) for im in rng.sample(stock, 6)]
    photos += [Image.new("RGB", (1000, 750), (rng.randint(0, 8),) * 3) for _ in range(2)]
    photos += [pocket_shot() for _ in range(3)]
    photos += [screenshot(i) for i in range(4)]
    photos += [receipt(i) for i in range(4)]
    rng.shuffle(photos)
    for old in out.glob("IMG_*.jpg"):
        old.unlink()
    paths = []
    for i, im in enumerate(photos):
        p = out / f"IMG_{first + i}.jpg"
        im.save(p, quality=88)
        paths.append(p)
    print(f"Built {len(paths)} photos in {out} ({len(stock)} stock + engineered dupes/blurry/junk/screenshots/receipts)")
    return paths


async def _fetch(page: int):
    async with httpx.AsyncClient(headers=UA, timeout=30, follow_redirects=True) as client:
        return await fetch_stock(client, page)


async def upload(paths: list[Path]):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from jevsort.photos import GooglePhotos

    gp = await GooglePhotos().connect()
    page = gp.page
    await page.keyboard.press("Escape")
    await page.goto("https://photos.google.com/")
    await page.wait_for_timeout(2000)
    async with page.expect_file_chooser(timeout=15000) as fc:
        await page.get_by_role("button", name="Create and add photos").click()
        await page.get_by_role("menuitem", name="Import photos from your computer").click()
    await (await fc.value).set_files([str(p) for p in paths])
    quality = page.get_by_role("button", name="Continue", exact=True)
    try:
        await quality.click(timeout=5000)
    except Exception:
        pass
    print(f"Uploading {len(paths)} photos... watch progress in the Chrome window.")
    await page.wait_for_timeout(5000)
    await gp.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--upload", action="store_true")
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--set", type=int, default=1, help="Set N uses Openverse page N, its own seed and folder")
    args = ap.parse_args()
    rng.seed(41 + args.set)
    out = OUT if args.set == 1 else OUT.with_name(f"{OUT.name}-{args.set}")
    paths = sorted(out.glob("IMG_*.jpg"))
    if args.rebuild or not paths:
        paths = build(out, args.set, 1000 * args.set)
    if args.upload:
        asyncio.run(upload(paths))


if __name__ == "__main__":
    main()
