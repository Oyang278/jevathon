import functools
import io

import imagehash
import numpy as np
import open_clip
import torch
from PIL import Image

DEFAULT_CATEGORIES = [
    "people and portraits",
    "pets and animals",
    "food and drinks",
    "nature and landscapes",
    "beach and ocean",
    "city and architecture",
    "documents and receipts",
    "screenshots",
    "cars and vehicles",
    "parties and events",
]
JUNK_PROMPTS = {
    "accidental": "an accidental photo of a pocket, floor or finger",
    "blurry": "a very blurry, out of focus photo",
}
GOOD_PROMPT = "a clear, intentional, well composed photo"
PROMPTS = {
    "screenshots": "a screenshot of a phone app or website user interface with text and buttons",
    "documents and receipts": "a photo of a paper document, receipt or printed page with text",
}


@functools.cache
def load_clip() -> tuple:
    """Load CLIP once per process; call early in a thread to overlap with browser work."""
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model, _, preprocess = open_clip.create_model_and_transforms("ViT-B-32", pretrained="laion2b_s34b_b79k", device=device)
    model.eval()
    return model, preprocess, open_clip.get_tokenizer("ViT-B-32"), device


class Clip:
    def __init__(self, categories: list[str]):
        self.model, self.preprocess, tokenizer, self.device = load_clip()
        self.categories = categories
        prompts = [PROMPTS.get(c.lower(), f"a photo of {c}") for c in categories] + list(JUNK_PROMPTS.values()) + [GOOD_PROMPT]
        with torch.no_grad():
            text = self.model.encode_text(tokenizer(prompts).to(self.device))
            self.text = text / text.norm(dim=-1, keepdim=True)

    @torch.no_grad()
    def label(self, images: list[Image.Image]) -> list[dict]:
        batch = torch.stack([self.preprocess(im) for im in images]).to(self.device)
        feats = self.model.encode_image(batch)
        feats = feats / feats.norm(dim=-1, keepdim=True)
        logits = (100 * feats @ self.text.T).float().cpu()
        n = len(self.categories)
        cat_probs = logits[:, :n].softmax(dim=-1)
        out = []
        for i in range(len(images)):
            top = cat_probs[i].topk(3)
            junk = {
                k: round(float(torch.stack([logits[i, n + j], logits[i, -1]]).softmax(0)[0]), 2)
                for j, k in enumerate(JUNK_PROMPTS)
            }
            out.append({
                "top_labels": {self.categories[j]: round(float(p), 2) for p, j in zip(top.values, top.indices)},
                "junk_likelihood": junk,
                "embedding": feats[i].float().cpu(),
            })
        return out


def sharpness(im: Image.Image) -> float:
    g = np.asarray(im.convert("L"), dtype=np.float32)
    lap = 4 * g[1:-1, 1:-1] - g[:-2, 1:-1] - g[2:, 1:-1] - g[1:-1, :-2] - g[1:-1, 2:]
    return float(lap.var())


def exposure(im: Image.Image) -> str:
    g = np.asarray(im.convert("L"), dtype=np.float32)
    return "nearly black" if g.mean() < 20 else "blank, almost one flat colour" if g.std() < 10 else "normal"


def shape(im: Image.Image) -> str:
    r = im.height / im.width
    return "tall phone-screen shape (typical of screenshots)" if r > 1.9 else "portrait" if r > 1.05 else "landscape" if r < 0.95 else "square"


def blur_level(s: float) -> str:
    return "very blurry" if s < 20 else "somewhat blurry" if s < 80 else "sharp"


def open_image(data: bytes) -> Image.Image:
    im = Image.open(io.BytesIO(data))
    im.load()
    return im.convert("RGB")


def phash(im: Image.Image) -> imagehash.ImageHash:
    return imagehash.phash(im)
