import asyncio
import gc
import io
import json
import time
from pathlib import Path

from PIL import Image
from rich.console import Console

from .models import Decision, FetchedPhoto, PhotoRef, Processor
from .photos import GooglePhotos

RESULTS = Path("results.jsonl")
console = Console()


def bar(p, width: int = 10) -> str:
    if not isinstance(p, (int, float)):
        return " " * (width + 5)
    filled = round(max(0.0, min(1.0, p)) * width)
    color = "green" if p >= 0.8 else "yellow" if p >= 0.5 else "red"
    return f"[{color}]{'█' * filled}{'░' * (width - filled)}[/] {p:4.0%}"


def load_results(path: Path = RESULTS) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def top_label(state: dict) -> str:
    labels = state.get("content_labels")
    if isinstance(labels, dict):
        return next(iter(labels), "")
    if isinstance(labels, list) and labels:
        first = labels[0]
        return str(first[0] if isinstance(first, (list, tuple)) else first.get("label", "") if isinstance(first, dict) else first)
    return ""


def feed_line(d: Decision) -> str:
    album = d.answers.get("album") or {}
    delete = d.answers.get("delete") or {}
    return (
        f"{d.id[:10]:<10}  {top_label(d.state):<22.22}  {(d.actions or ['keep'])[0]:<26.26}"
        f"album {bar(album.get('confidence'))}  delete {bar(delete.get('noul'))}  {d.latency_ms:5.0f}ms"
    )


async def fetch_batch(gp: GooglePhotos, refs: list[PhotoRef], concurrency: int = 16) -> list[FetchedPhoto]:
    sem = asyncio.Semaphore(concurrency)

    async def one(ref: PhotoRef) -> FetchedPhoto | None:
        async with sem:
            try:
                data = await gp.download(ref.thumb)
                return FetchedPhoto(ref, Image.open(io.BytesIO(data)).convert("RGB"))
            except Exception as e:
                console.print(f"[dim]skip {ref.id[:10]}: {e}[/]")
                return None

    return [p for p in await asyncio.gather(*(one(r) for r in refs)) if p]


async def scan(gp: GooglePhotos, processor: Processor, limit: int, batch_size: int, results: Path = RESULTS) -> int:
    prior = load_results(results)
    processor.prime(prior)
    done = {r["id"] for r in prior}
    if done:
        console.print(f"[dim]Resuming: {len(done)} photos already in {results}[/]")
    refs = aiter(gp.collect_photos(limit, skip=done))

    async def next_batch() -> list[FetchedPhoto] | None:
        chunk = []
        async for ref in refs:
            chunk.append(ref)
            if len(chunk) >= batch_size:
                break
        return await fetch_batch(gp, chunk) if chunk else None

    total, n, t0 = 0, 0, time.perf_counter()
    pending = asyncio.create_task(next_batch())
    with results.open("a") as out:
        while (batch := await pending) is not None:
            pending = asyncio.create_task(next_batch())
            if not batch:
                continue
            n += 1
            bt = time.perf_counter()
            decisions = await processor.process(batch)
            refs_by_id = {p.ref.id: p.ref for p in batch}
            del batch
            for d in decisions:
                if d.extra.get("error"):
                    console.print(f"[red]jev failed {d.id[:10]}: {d.extra['error']} (will retry next scan)[/]")
                    continue
                ref = refs_by_id.get(d.id)
                rec = {
                    "id": d.id, "label": ref.label if ref else "", "thumb": ref.thumb if ref else "",
                    "actions": d.actions, "answers": d.answers, "state": d.state, "latency_ms": d.latency_ms,
                    "phash": d.phash, "sharpness": d.sharpness, **({"extra": d.extra} if d.extra else {}),
                }
                out.write(json.dumps(rec, default=str) + "\n")
                console.print(feed_line(d))
            out.flush()
            total += len(decisions)
            console.print(
                f"[bold cyan]batch {n}: {len(decisions)} photos in {time.perf_counter() - bt:.1f}s · {processor.summary()}[/]"
            )
            del decisions, refs_by_id
            gc.collect()
    console.print(f"[bold green]Done: {total} new photos in {time.perf_counter() - t0:.1f}s. Run `jevsort apply` to see the plan.[/]")
    return total


def plan(records: list[dict]) -> dict[str, list[str]]:
    albums: dict[str, list[str]] = {}
    for r in records:
        for album in dict.fromkeys(r.get("actions") or []):
            if album:
                albums.setdefault(album, []).append(r["id"])
    return dict(sorted(albums.items(), key=lambda kv: -len(kv[1])))


class Journal:
    """Undo log: albums that existed before, albums jevsort created, and pre-change contents of albums it touched."""

    def __init__(self, path: Path):
        self.path = path
        self.data = json.loads(path.read_text()) if path.exists() else None

    def start(self, albums_before: dict[str, str]):
        if self.data is None:
            self.data = {"albums_before": albums_before, "planned": [], "created": {}, "snapshots": {}}

    def save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1))
        tmp.replace(self.path)


async def in_tabs(gp: GooglePhotos, jobs: list, tabs: int):
    """Run `job(tab)` coroutines across up to `tabs` browser tabs in parallel."""
    queue: asyncio.Queue = asyncio.Queue()
    for job in jobs:
        queue.put_nowait(job)

    async def worker():
        tab = await gp.new_tab()
        try:
            while not queue.empty():
                await queue.get_nowait()(tab)
        finally:
            await tab.close()

    await asyncio.gather(*(worker() for _ in range(min(tabs, len(jobs)))))


async def apply(gp: GooglePhotos, albums: dict[str, list[str]], journal: Journal, tabs: int = 12):
    before = await gp.albums_info()
    links = {t: p for t, (p, _) in before.items()}
    journal.start(links)
    journal.data["planned"] = sorted(set(journal.data["planned"]) | set(albums))
    for title, path in links.items():
        if title in albums and title not in journal.data["created"] and title not in journal.data["snapshots"]:
            journal.data["snapshots"][title] = {"path": path, "ids": sorted(await gp.grid_ids(path))}
    journal.save()
    t0 = time.perf_counter()
    added: dict[str, int] = {}

    def job(title: str, ids: list[str]):
        def record(path: str):
            journal.data["created"][title] = path
            journal.save()

        async def run(tab: GooglePhotos):
            t = time.perf_counter()
            try:
                selected = await tab.select("/", set(ids))
                if not selected:
                    raise RuntimeError("none of its photos were found in the library grid")
                await tab.add_selection_to_album(title, create=title not in links, on_created=record)
                added[title] = len(selected)
                missing = f" ([yellow]{len(ids) - len(selected)} not found[/])" if len(selected) < len(ids) else ""
                console.print(f"  [green]✓[/] {title}: {len(selected)} photos{missing} in {time.perf_counter() - t:.1f}s")
            except Exception as e:
                console.print(f"  [red]✗ {title}: {str(e).splitlines()[0]}[/]")

        return run

    await in_tabs(gp, [job(t, ids) for t, ids in albums.items()], tabs)
    elapsed = time.perf_counter() - t0
    for _ in range(6):
        after = await gp.albums_info()
        short = [
            f"{t} ({after.get(t, ('', 0))[1]}/{n})" for t, n in added.items()
            if after.get(t, ("", 0))[1] < (n if t not in before else max(before[t][1], n))
        ]
        if not short:
            break
        await asyncio.sleep(2)
    if short:
        console.print(f"[red]Albums with fewer items than selected: {', '.join(short)}. Re-run apply to fill them.[/]")
    console.print(f"[bold green]Applied {len(added)}/{len(albums)} albums in {elapsed:.1f}s. Undo with `jevsort restore`.[/]")


async def restore(gp: GooglePhotos, journal: Journal, yes: bool, tabs: int = 12):
    if journal.data is None:
        console.print(f"Nothing to restore: no {journal.path}.")
        return
    d = journal.data
    before = set(d["albums_before"].values())

    async def pending() -> tuple[dict, dict]:
        links = await gp.album_links()
        doomed = {t: p for t, p in d["created"].items() if p in links.values()}
        doomed |= {t: p for t, p in links.items() if t in d["planned"] and p not in before}
        extras = {}
        for title, snap in d["snapshots"].items():
            added = await gp.grid_ids(snap["path"]) - set(snap["ids"])
            if added:
                extras[title] = (snap["path"], added)
        return doomed, extras

    doomed, extras = await pending()
    for title in doomed:
        console.print(f"  delete album [bold]{title}[/] (photos stay in the library)")
    for title, (_, added) in extras.items():
        console.print(f"  remove {len(added)} added photos from [bold]{title}[/]")
    if not doomed and not extras:
        console.print("Already at the initial state.")
    if not yes:
        console.print("[yellow]Dry run. Re-run `jevsort restore --yes` to undo.[/]")
        return

    def guarded(title, action):
        async def run(tab):
            try:
                console.print(f"  [green]✓[/] {await action(tab)}")
            except Exception as e:
                console.print(f"  [red]✗ {title}: {str(e).splitlines()[0]}[/]")
        return run

    def delete(title, path):
        async def action(tab):
            await tab.delete_album(path)
            return f"deleted {title}"
        return guarded(title, action)

    def remove(title, path, ids):
        async def action(tab):
            n = await tab.remove_from_album(path, ids)
            if n < len(ids):
                raise RuntimeError(f"only selected {n}/{len(ids)} added photos")
            return f"removed {n} photos from {title}"
        return guarded(title, action)

    t0 = time.perf_counter()
    for attempt in range(3):
        jobs = [delete(t, p) for t, p in doomed.items()] + [remove(t, p, ids) for t, (p, ids) in extras.items()]
        if not jobs:
            break
        if attempt:
            console.print(f"[yellow]Retrying {len(jobs)} leftover change(s) with fewer tabs...[/]")
        await in_tabs(gp, jobs, max(1, tabs >> attempt))
        doomed, extras = await pending()
    if doomed or extras:
        console.print(f"[red]Still present: {', '.join([*doomed, *(f'photos added to {t}' for t in extras)])}. Re-run restore.[/]")
        return
    journal.path.rename(journal.path.with_name(f"{journal.path.stem}.restored-{int(time.time())}.json"))
    console.print(f"[bold green]Restored initial state in {time.perf_counter() - t0:.1f}s.[/]")
