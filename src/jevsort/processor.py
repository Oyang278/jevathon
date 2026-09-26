import asyncio

import imagehash

from .jev import Jev
from .models import DELETE_ALBUM, REVIEW_ALBUM, Decision, FetchedPhoto
from .signals import DEFAULT_CATEGORIES, Clip, blur_level, exposure, phash, shape, sharpness

DUP_DISTANCE = 8
DUP_SIMILARITY = 0.97
TEXT_DUP_SIMILARITY = 0.995
TEXT_HEAVY = {"screenshots", "documents and receipts"}
MAX_CHOICES = 255


def album_options(albums: list[str]) -> dict[str, tuple[str, str]]:
    """Maps choice key -> (description for Jev, album title)."""
    existing = {a.lower() for a in albums}
    opts = {f"a{i}": (f"Existing album '{a}'", a) for i, a in enumerate(albums) if not a.startswith("Jev:")}
    for i, c in enumerate(DEFAULT_CATEGORIES):
        title = c.capitalize()
        if title.lower() not in existing:
            opts[f"n{i}"] = (f"Create a new album '{title}' for photos of {c}", title)
    opts = dict(list(opts.items())[: MAX_CHOICES - 1])
    opts["none"] = ("Does not clearly belong in any album; leave it unsorted", "")
    return opts


def questions(opts: dict) -> dict:
    return {
        "album": {
            "type": "choice",
            "instructions": "Which album should this photo be filed into? Prefer an existing album when it fits.",
            "criteria": {k: v[0] for k, v in opts.items()},
        },
        "delete": {
            "type": "noul",
            "instructions": "Should this photo be proposed to the user for deletion?",
            "criteria": {
                "true": "It is the worse copy of a near-duplicate, or it is junk: very blurry, accidental, or blank",
                "false": "It is a normal photo worth keeping, even if imperfect, or it is the better copy of a duplicate",
            },
        },
    }


def decide(album_ans: dict, delete_p: float, opts: dict, threshold: float) -> list[str]:
    actions = []
    if delete_p >= 0.8:
        actions.append(DELETE_ALBUM)
    elif delete_p >= 0.5:
        actions.append(REVIEW_ALBUM)
    key = album_ans.get("choice", "none")
    if key in opts and key != "none" and delete_p < 0.8:
        actions.append(opts[key][1] if album_ans.get("confidence", 0) >= threshold else REVIEW_ALBUM)
    return list(dict.fromkeys(actions))


class JevProcessor:
    def __init__(self, albums: list[str], threshold: float = 0.6):
        self.threshold = threshold
        self.opts = album_options(albums)
        self.questions = questions(self.opts)
        categories = [a for a in albums if not a.startswith("Jev:")] + DEFAULT_CATEGORIES
        self.clip = Clip(list({c.lower(): c for c in reversed(categories)}.values())[::-1])
        self.jev = Jev()
        self.hashes: dict[str, tuple[imagehash.ImageHash, float]] = {}
        self.embeddings: dict = {}
        self.photos = 0

    def _near_duplicate(self, pid: str, h: imagehash.ImageHash, emb, min_sim: float) -> dict | None:
        best = None
        for oid, (oh, os_) in self.hashes.items():
            d = h - oh
            if oid == pid or d > DUP_DISTANCE:
                continue
            other = self.embeddings.get(oid)
            sim = float(emb @ other) if other is not None else None
            if sim is not None and sim < min_sim:
                continue
            if best is None or (sim or 0) > (best["visual_similarity"] or 0):
                best = {"hash_distance": int(d), "visual_similarity": None if sim is None else round(sim, 3), "_sharpness": os_}
        return best

    def prime(self, prior: list[dict]) -> None:
        for r in prior:
            if r.get("phash") and r.get("sharpness") is not None:
                self.hashes[r["id"]] = (imagehash.hex_to_hash(r["phash"]), float(r["sharpness"]))

    def _signals(self, images: list) -> tuple[list[dict], list[tuple[imagehash.ImageHash, float]], list[str]]:
        return self.clip.label(images), [(phash(im), sharpness(im)) for im in images], [exposure(im) for im in images]

    async def process(self, batch: list[FetchedPhoto]) -> list[Decision]:
        if not batch:
            return []
        labels, hs, exposures = await asyncio.to_thread(self._signals, [p.image for p in batch])
        for p, lab, hsh in zip(batch, labels, hs):
            self.hashes[p.ref.id] = hsh
            self.embeddings[p.ref.id] = lab.pop("embedding")
        states = []
        for p, lab, (h, s), exp in zip(batch, labels, hs, exposures):
            min_sim = TEXT_DUP_SIMILARITY if next(iter(lab["top_labels"]), "") in TEXT_HEAVY else DUP_SIMILARITY
            dup = self._near_duplicate(p.ref.id, h, self.embeddings[p.ref.id], min_sim)
            if dup:
                dup["this_is_the_worse_copy"] = s <= dup.pop("_sharpness")
            states.append({
                "google_photos_label": p.ref.label,
                "shape": shape(p.image),
                "sharpness": blur_level(s),
                "exposure": exp,
                "content_labels": lab["top_labels"],
                "junk_likelihood": lab["junk_likelihood"],
                "near_duplicate": dup,
            })
        refs = [p.ref for p in batch]
        del batch
        results = await asyncio.gather(*(self.jev.ask(st, self.questions) for st in states), return_exceptions=True)
        decisions = []
        for ref, st, (h, s), res in zip(refs, states, hs, results):
            if isinstance(res, BaseException):
                ans, latency, actions, extra = {}, 0.0, [], {"error": str(res)[:300]}
            else:
                ans, latency = res
                album = ans.get("album", {})
                actions = decide(album, ans.get("delete", {}).get("noul", 0.0), self.opts, self.threshold)
                extra = {"album_title": self.opts.get(album.get("choice"), ("", ""))[1]}
            decisions.append(Decision(
                id=ref.id, actions=actions, answers=ans, state=st, latency_ms=round(latency * 1000, 1),
                phash=str(h), sharpness=round(s, 1), extra=extra,
            ))
        self.photos += len(decisions)
        return decisions

    def summary(self) -> str:
        return f"{self.photos} photos · {self.jev.calls} Jev calls · ${self.jev.cost:.5f} · avg {self.jev.avg_latency_ms:.0f}ms"

    async def close(self) -> None:
        await self.jev.close()
