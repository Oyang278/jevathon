# Third-party notices

jevsort itself is MIT licensed (see `LICENSE`). This repository does not bundle any third-party code,
model weights or images; the components below are installed or downloaded separately and keep their own
licenses.

## Python dependencies

Direct dependencies from `pyproject.toml`, installed from PyPI by `uv sync`. Licenses are taken from the
installed package metadata (versions from `uv.lock`). Transitive dependencies are listed in `uv.lock` and
have their own licenses.

| Package | Version | License (package metadata) |
| --- | --- | --- |
| httpx | 0.28.1 | BSD-3-Clause |
| imagehash | 4.3.2 | "2-clause BSD License" (free text, no SPDX identifier; the bundled LICENSE reads as BSD-2-Clause) |
| numpy | 2.5.3 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 (NumPy plus bundled components) |
| open-clip-torch | 3.3.0 | MIT |
| pillow | 12.3.0 | MIT-CMU |
| playwright | 1.63.0 | Apache-2.0 |
| python-dotenv | 1.2.3 | BSD-3-Clause |
| rich | 15.0.0 | MIT |
| torch | 2.14.0 | Apache-2.0 AND Apache-2.0 WITH LLVM-exception AND BSD-2-Clause AND BSD-3-Clause AND BSL-1.0 AND MIT (PyTorch's own LICENSE is BSD-3-Clause style; the rest covers bundled components) |

## CLIP model weights

`signals.py` loads OpenCLIP `ViT-B-32` with the `laion2b_s34b_b79k` weights, downloaded at runtime from
Hugging Face ([laion/CLIP-ViT-B-32-laion2B-s34B-b79K](https://huggingface.co/laion/CLIP-ViT-B-32-laion2B-s34B-b79K))
and cached locally. The model card lists the license as MIT. It also describes the model as a research
output trained on the uncurated LAION-2B dataset and, following OpenAI's CLIP guidance, considers deployed
use cases out of scope; see the model card for details.

## Services

- **Jev by TypeSafe AI** is a proprietary hosted API. It is not included in this repository; using it
  requires your own TypeSafe API key and is governed by TypeSafe AI's terms.
- **Google Chrome and Google Photos** are third-party products and services used through your own Google
  account and subject to Google's terms. jevsort automates the Google Photos web UI; it is not an official
  Google integration.

## Demo images

`scripts/demo_set.py` searches the [Openverse](https://openverse.org) API for Creative Commons licensed
Flickr photos and downloads them at runtime into `/tmp/jevsort-demo`, along with generated images. These
photos are not redistributed in this repository and each keeps its own CC license (the search includes
all CC licenses, including NonCommercial and NoDerivatives variants). The script does not record
attribution, so check each image's license on Openverse before sharing the demo set or anything derived
from it.
