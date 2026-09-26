import argparse
import asyncio
from pathlib import Path

from dotenv import load_dotenv

from . import pipeline
from .photos import GooglePhotos
from .pipeline import console


async def scan(args):
    from .processor import JevProcessor
    from .signals import load_clip

    clip = asyncio.create_task(asyncio.to_thread(load_clip))
    gp = await GooglePhotos().connect()
    albums = await gp.list_albums()
    console.print(f"[bold]Existing albums:[/] {', '.join(albums) or '(none)'}")
    await clip
    processor = JevProcessor(albums, threshold=args.threshold)
    tab = await gp.new_tab(tall=True)
    try:
        await pipeline.scan(tab, processor, args.limit, args.batch, Path(args.results))
    finally:
        await processor.close()
        await tab.close()
        await gp.close()


async def apply(args):
    albums = pipeline.plan(pipeline.load_results(Path(args.results)))
    if not albums:
        console.print(f"Nothing to apply in {args.results}.")
        return
    for album, ids in albums.items():
        console.print(f"[bold]{album}[/]: {len(ids)} photos")
    if not args.yes:
        console.print("[yellow]Dry run. Re-run with --yes to add photos to albums. Nothing is ever deleted.[/]")
        return
    gp = await GooglePhotos().connect()
    try:
        await pipeline.apply(gp, albums, pipeline.Journal(Path(args.log)), args.tabs)
    finally:
        await gp.close()


async def restore(args):
    gp = await GooglePhotos().connect()
    try:
        await pipeline.restore(gp, pipeline.Journal(Path(args.log)), args.yes, args.tabs)
    finally:
        await gp.close()


async def albums(_args):
    gp = await GooglePhotos().connect()
    try:
        names = await gp.list_albums()
        console.print(f"[bold]{len(names)} albums:[/]", *names, sep="\n  ")
    finally:
        await gp.close()


async def ping(_args):
    from .jev import Jev

    jev = Jev()
    ans, latency = await jev.ask(
        {"content_labels": {"beach and ocean": 0.81}, "sharpness": "sharp"},
        {"album": {"type": "choice", "instructions": "Which album?", "criteria": {"beach": "Beach", "food": "Food"}}},
    )
    console.print(ans, f"{latency * 1000:.0f}ms")
    await jev.close()


def main():
    load_dotenv()
    ap = argparse.ArgumentParser(prog="jevsort", description="Organise Google Photos with Jev decisions")
    ap.add_argument("--results", default=str(pipeline.RESULTS), help="Results file (default: %(default)s)")
    ap.add_argument("--log", default="apply_log.json", help="Undo journal written by apply (default: %(default)s)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan", help="Classify photos in streaming batches into results.jsonl (resumable)")
    s.add_argument("--limit", type=int, default=300, help="New photos to process")
    s.add_argument("--batch", type=int, default=100)
    s.add_argument("--threshold", type=float, default=0.6, help="Album confidence needed to auto-file")
    a = sub.add_parser("apply", help="Show the album plan; with --yes, add photos to albums (never deletes)")
    a.add_argument("--yes", action="store_true")
    a.add_argument("--tabs", type=int, default=12, help="Albums processed in parallel browser tabs")
    r = sub.add_parser("restore", help="Undo apply: delete albums it created, remove photos it added (dry run without --yes)")
    r.add_argument("--yes", action="store_true")
    r.add_argument("--tabs", type=int, default=12)
    sub.add_parser("albums", help="List existing albums (smoke test for the Chrome connection)")
    sub.add_parser("ping", help="Check the Jev key works")
    args = ap.parse_args()
    asyncio.run({"scan": scan, "apply": apply, "restore": restore, "albums": albums, "ping": ping}[args.cmd](args))


if __name__ == "__main__":
    main()
