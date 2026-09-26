import asyncio
import re
from collections.abc import AsyncIterator, Container

from playwright.async_api import BrowserContext, Page, async_playwright

from .models import PhotoRef

BASE = "https://photos.google.com"
CHROME_CMD = (
    '"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" '
    '--remote-debugging-port=9222 --user-data-dir="$HOME/.jevathon-chrome"'
)

COLLECT_JS = """
() => [...document.querySelectorAll('a[href*="/photo/"]')].map(a => {
  const urls = [a, ...a.querySelectorAll('*')].map(d => (d.style && d.style.backgroundImage) || '')
    .map(b => (b.match(/url\\(["']?(.*?)["']?\\)/) || [])[1]).filter(Boolean);
  return {
    id: a.getAttribute('href').split('/photo/')[1].split(/[?/#]/)[0],
    label: a.getAttribute('aria-label') || '',
    thumb: urls.find(u => u.includes('usercontent')) || urls[0] || null,
  };
})
"""

RENDERED_JS = """
() => [...document.querySelectorAll('a[href*="/photo/"]')].map(a => ({
  id: a.getAttribute('href').split('/photo/')[1].split(/[?/#]/)[0],
  checked: a.parentElement.querySelector('[role=checkbox]')?.getAttribute('aria-checked') === 'true',
}))
"""

TICK_JS = """
ids => {
  const want = new Set(ids), seen = [];
  for (const a of document.querySelectorAll('a[href*="/photo/"]')) {
    const id = a.getAttribute('href').split('/photo/')[1].split(/[?/#]/)[0];
    const cb = want.has(id) && a.parentElement.querySelector('[role=checkbox]');
    if (!cb) continue;
    seen.push(id);
    if (cb.getAttribute('aria-checked') !== 'true')
      for (const type of ['mousedown', 'mouseup', 'click'])
        cb.dispatchEvent(new MouseEvent(type, {bubbles: true, cancelable: true, view: window}));
  }
  return seen;
}
"""

SCROLL_JS = """
() => {
  let el = document.querySelector('a[href*="/photo/"]');
  while (el && el !== document.body) {
    const s = getComputedStyle(el);
    if (/(auto|scroll)/.test(s.overflowY) && el.scrollHeight > el.clientHeight + 10) break;
    el = el.parentElement;
  }
  const target = el && el !== document.body ? el : document.scrollingElement;
  const before = target.scrollTop;
  target.scrollBy(0, target.clientHeight * 0.8);
  return target.scrollTop !== before;
}
"""


class GooglePhotos:
    def __init__(self, base: str = BASE):
        self.base = base
        self.pw = None

    async def connect(self, cdp_url: str = "http://localhost:9222") -> "GooglePhotos":
        self.pw = await async_playwright().start()
        try:
            browser = await self.pw.chromium.connect_over_cdp(cdp_url)
        except Exception as e:
            await self.pw.stop()
            raise SystemExit(
                f"Can't reach Chrome at {cdp_url}. Quit Chrome, then start it with:\n  {CHROME_CMD}\n"
                "and log into photos.google.com in that window once."
            ) from e
        ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = next((p for p in ctx.pages if "photos.google.com" in p.url), None) or await ctx.new_page()
        await page.bring_to_front()
        return self.attach(page, ctx)

    def attach(self, page: Page, ctx: BrowserContext | None = None) -> "GooglePhotos":
        self.page, self.ctx = page, ctx or page.context
        return self

    async def goto(self, path: str = ""):
        await self.page.goto(f"{self.base}{path}", wait_until="domcontentloaded")
        if "accounts.google.com" in self.page.url or "/photos/about" in self.page.url:
            raise SystemExit(
                "Not logged into Google Photos. Log in at photos.google.com in the debugging Chrome window, then retry."
            )

    async def list_albums(self) -> list[str]:
        return sorted(await self.album_links())

    async def collect_photos(self, limit: int, skip: Container[str] = ()) -> AsyncIterator[PhotoRef]:
        """Scroll the virtualized library grid, yielding up to `limit` new photos (videos and `skip` ids excluded)."""
        await self.goto()
        await self.page.wait_for_selector('a[href*="/photo/"]', timeout=20000)
        seen, yielded, stale = set(), 0, 0
        while yielded < limit and stale < 4:
            fresh = [p for p in await self.page.evaluate(COLLECT_JS) if p["thumb"] and p["id"] not in seen]
            stale = 0 if fresh else stale + 1
            for p in fresh:
                seen.add(p["id"])
                if p["id"] in skip or p["label"].lower().startswith("video"):
                    continue
                yield PhotoRef(p["id"], p["label"], p["thumb"])
                yielded += 1
                if yielded >= limit:
                    return
            if not await self._scroll():
                stale += 1
            await asyncio.sleep(0.25)

    async def download(self, thumb: str, size: int = 512) -> bytes:
        url = re.sub(r"=[^/]*$", "", thumb) + f"=w{size}-h{size}"
        for attempt in range(3):
            try:
                res = await self.ctx.request.get(url, timeout=20000)
            except Exception:
                if attempt == 2:
                    raise
            else:
                if res.ok:
                    return await res.body()
                if attempt == 2 or (res.status != 429 and res.status < 500):
                    raise RuntimeError(f"HTTP {res.status} for {url}")
            await asyncio.sleep(0.5 * 2**attempt)
        raise AssertionError("unreachable")

    async def new_tab(self, tall: bool = False) -> "GooglePhotos":
        """`tall` renders more of the grid per scroll step; it speeds up one tab but slows many parallel ones.
        Uses CDP emulation because page.set_viewport_size resizes the real window in headful Chrome."""
        page = await self.ctx.new_page()
        tab = GooglePhotos(self.base).attach(page, self.ctx)
        if tall:
            tab.cdp = await self.ctx.new_cdp_session(page)
            await tab.cdp.send("Emulation.setDeviceMetricsOverride", {"width": 2400, "height": 4000, "deviceScaleFactor": 1, "mobile": False})
        return tab

    async def _scroll(self) -> bool:
        if await self.page.evaluate(SCROLL_JS):
            return True
        box = self.page.viewport_size or {"width": 1200, "height": 800}
        await self.page.mouse.move(box["width"] / 2, box["height"] / 2)
        await self.page.mouse.wheel(0, box["height"] * 0.8)
        return False

    async def _open_grid(self, path: str) -> bool:
        await self.goto(path)
        try:
            await self.page.wait_for_selector('a[href*="/photo/"]', timeout=8000)
            return True
        except Exception:
            return False

    async def album_links(self) -> dict[str, str]:
        """Album title -> path (e.g. /album/AF1Qip...)."""
        return {t: p for t, (p, _) in (await self.albums_info()).items()}

    async def albums_info(self) -> dict[str, tuple[str, int]]:
        """Album title -> (path, item count) from the albums page."""
        await self.goto("/albums")
        album = self.page.locator('a[href*="/album/"]').filter(has_text=re.compile(r"\d+ items?"))
        empty = self.page.get_by_text("The albums you create are shown here")
        try:
            await album.or_(empty).first.wait_for(timeout=15000)
        except Exception:
            return {}
        rows = await self.page.eval_on_selector_all(
            'a[href*="/album/"]',
            """els => els.map(e => {
              const lines = (e.innerText || '').split('\\n').map(s => s.trim());
              const count = (lines.find(s => /^\\d+ items?$/.test(s)) || '0').split(' ')[0];
              return [lines[0], '/album/' + e.getAttribute('href').split('/album/')[1].split(/[?/#]/)[0], +count];
            })""",
        )
        return {t: (p, n) for t, p, n in rows if t}

    async def grid_ids(self, path: str) -> set[str]:
        """All photo ids in a grid (library or album). Ids are context-specific: album ids differ from library ids."""
        if not await self._open_grid(path):
            return set()
        ids, stale = set(), 0
        while stale < 3:
            fresh = {r["id"] for r in await self.page.evaluate(RENDERED_JS)} - ids
            ids |= fresh
            stale = 0 if fresh else stale + 1
            if not await self._scroll():
                stale += 1
            await asyncio.sleep(0.2)
        return ids

    async def select(self, path: str, ids: set[str]) -> set[str]:
        """Tick every photo in `ids` on the grid at `path` (all rendered tiles per scroll step in one JS call)."""
        if not await self._open_grid(path):
            return set()
        todo, explored, stale = set(ids), set(), 0
        while todo and stale < 4:
            rendered: list[dict] = []
            for attempt in range(4):
                seen = set(await self.page.evaluate(TICK_JS, list(todo)))
                await self.page.wait_for_timeout(120 + 200 * attempt if seen else 0)
                rendered = await self.page.evaluate(RENDERED_JS)
                todo -= {r["id"] for r in rendered if r["checked"]}
                if not seen & todo:
                    break
            fresh = {r["id"] for r in rendered} - explored
            explored |= fresh
            stale = 0 if fresh else stale + 1
            if todo and not await self._scroll():
                stale += 1
            await asyncio.sleep(0.15)
        return set(ids) - todo

    async def add_selection_to_album(self, album: str, create: bool, on_created=None) -> str | None:
        """Add the current selection to an album. When `create`, Google makes the (untitled) album as soon as
        "New album" is clicked, so `on_created(path)` fires before titling; returns the new album's path."""
        page = self.page
        await page.get_by_role("button", name="Create or add to album").click()
        await page.get_by_role("menuitem", name="Album", exact=True).click()
        dialog = page.get_by_role("dialog").last
        if not create:
            await dialog.get_by_role("option", name=re.compile(rf"^{re.escape(album)} ·")).first.click(timeout=10000)
            await dialog.wait_for(state="hidden", timeout=10000)
            await page.wait_for_timeout(500)
            return None
        await dialog.get_by_role("option", name=re.compile("New album", re.I)).click(timeout=10000)
        await page.wait_for_url(re.compile(r"/album/"), timeout=30000)
        path = "/album/" + page.url.split("/album/")[1].split("/")[0].split("?")[0]
        if on_created:
            on_created(path)
        title = page.get_by_role("textbox", name="Edit album name")
        await title.fill(album, timeout=30000)
        done = page.get_by_role("button", name="Done", exact=True)
        await done.click()
        await done.wait_for(state="hidden", timeout=15000)
        await page.wait_for_timeout(300)
        return path

    async def delete_album(self, path: str):
        """Deletes the album only; its photos stay in the library."""
        await self.goto(path)
        await self.page.get_by_role("button", name="More options").last.click()
        await self.page.get_by_role("menuitem", name="Delete album").click()
        await self.page.get_by_role("button", name="Delete", exact=True).click()
        await self.page.wait_for_url(lambda url: path not in url, timeout=10000)

    async def remove_from_album(self, path: str, ids: set[str]) -> int:
        selected = await self.select(path, ids)
        if selected:
            await self.page.get_by_role("button", name="More options").last.click()
            await self.page.get_by_role("menuitem", name=re.compile("Remove from album")).click()
            confirm = self.page.get_by_role("button", name="Remove", exact=True)
            try:
                await confirm.click(timeout=2000)
            except Exception:
                pass
            await self.page.get_by_role("button", name="Clear selection").wait_for(state="hidden", timeout=10000)
            await self.page.wait_for_timeout(300)
        return len(selected)

    async def close(self):
        if self.pw:
            await self.pw.stop()
        else:
            await self.page.close()
