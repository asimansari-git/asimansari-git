#!/usr/bin/env python3
"""
One Piece Anime GitHub Profile SVG Builder
Compiles modular SVG templates from `templates/` into standalone GitHub-safe
SVGs in `assets/` with Pillow-optimized base64 PNG artwork and optional live
GitHub GraphQL telemetry.
"""

import base64
import io
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, Tuple

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "assets" / "raw"
TEMPLATE_DIR = REPO_ROOT / "templates"
OUT_DIR = REPO_ROOT / "assets"

# Target max (width, height) for crisp Retina-ready embedding while keeping each SVG < 600KB
ASSET_SPECS: Dict[str, Tuple[str, Tuple[int, int]]] = {
    "IMG_LUFFY_HERO": ("luffy-hero.png", (380, 440)),
    "IMG_MONSTER_TRIO": ("monster-trio.png", (380, 360)),
    "IMG_NICO_ROBIN": ("nico-robin.png", (340, 440)),
    "IMG_THOUSAND_SUNNY": ("thousand-sunny.png", (260, 260)),
    "IMG_STRAW_HAT_CREW": ("straw-hat-crew.png", (360, 320)),
    "IMG_STRAW_HAT_FLAG": ("straw-hat-flag.png", (160, 160)),
    "IMG_ROGER_FLAG": ("roger-flag.png", (160, 160)),
    "IMG_STRAW_HAT": ("straw-hat.png", (120, 120)),
    "IMG_CHIBI_LUFFY": ("chibi-luffy.png", (120, 160)),
    "IMG_CHIBI_ZORO": ("chibi-zoro.png", (120, 160)),
    "IMG_CHIBI_NAMI": ("chibi-nami.png", (120, 160)),
    "IMG_CHIBI_USOPP": ("chibi-usopp.png", (120, 160)),
    "IMG_CHIBI_SANJI": ("chibi-sanji.png", (120, 160)),
    "IMG_CHIBI_CHOPPER": ("chibi-chopper.png", (120, 160)),
    "IMG_CHIBI_ROBIN": ("chibi-robin.png", (120, 160)),
    "IMG_CHIBI_FRANKY": ("chibi-franky.png", (120, 160)),
    "IMG_CHIBI_BROOK": ("chibi-brook.png", (120, 160)),
    "IMG_CHIBI_JINBE": ("chibi-jinbe.png", (120, 160)),
}


def encode_png_asset(path: Path, max_size: Tuple[int, int]) -> str:
    """Resize and quantize/optimize PNG asset into a compact base64 data URI."""
    if not path.exists():
        raise FileNotFoundError(f"Missing raw asset: {path}")

    with Image.open(path) as img:
        img = img.convert("RGBA")
        img.thumbnail(max_size, Image.Resampling.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True, compress_level=9)
        raw_bytes = buf.getvalue()

        # If a single portrait still exceeds 180KB, apply adaptive palette quantization with alpha preservation
        if len(raw_bytes) > 180_000:
            q_img = img.quantize(colors=256, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.FLOYDSTEINBERG)
            q_buf = io.BytesIO()
            q_img.save(q_buf, format="PNG", optimize=True, compress_level=9)
            if len(q_buf.getvalue()) < len(raw_bytes):
                raw_bytes = q_buf.getvalue()

    b64 = base64.b64encode(raw_bytes).decode("ascii")
    return f"data:image/png;base64,{b64}"


def fetch_github_stats(username: str, token: str) -> Dict[str, str]:
    """Query GitHub GraphQL API for live profile metrics. Falls back to verified NanoHat defaults."""
    defaults = {
        "KPI_1_VAL": "93.98%",
        "KPI_1_LABEL": "NANOHAT ACC",
        "KPI_2_VAL": "595.7ms",
        "KPI_2_LABEL": "MEDIAN P50",
        "KPI_3_VAL": "10 TOOLS",
        "KPI_3_LABEL": "ZERO-SHELL CLI",
        "KPI_4_VAL": "v4.1.2",
        "KPI_4_LABEL": "FEDORA AGENT",
    }

    if not token:
        return defaults

    query = """
    query($login: String!) {
      user(login: $login) {
        repositories(first: 100, ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC) {
          totalCount
          nodes {
            stargazerCount
          }
        }
        contributionsCollection {
          totalCommitContributions
          restrictedContributionsCount
        }
      }
    }
    """
    payload = json.dumps({"query": query, "variables": {"login": username}}).encode("utf-8")
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "asimansari-git-profile-builder",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        user = data.get("data", {}).get("user")
        if not user:
            return defaults

        repos_data = user["repositories"]
        total_repos = repos_data["totalCount"]
        total_stars = sum(n["stargazerCount"] for n in repos_data.get("nodes", []))
        contrib = user["contributionsCollection"]
        total_commits = contrib["totalCommitContributions"] + contrib["restrictedContributionsCount"]

        return {
            "KPI_1_VAL": f"{total_commits:,}",
            "KPI_1_LABEL": "COMMITS (1Y)",
            "KPI_2_VAL": f"{total_repos}",
            "KPI_2_LABEL": "PUBLIC REPOS",
            "KPI_3_VAL": f"{total_stars:,}",
            "KPI_3_LABEL": "TOTAL STARS",
            "KPI_4_VAL": "93.98%",
            "KPI_4_LABEL": "NANOHAT ACC",
        }
    except (urllib.error.URLError, KeyError, json.JSONDecodeError) as exc:
        print(f"[warn] GitHub GraphQL fetch skipped ({exc}); using verified defaults.", file=sys.stderr)
        return defaults


def build_all() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Encoding raw anime PNG assets...")
    asset_uris: Dict[str, str] = {}
    for token_name, (filename, max_size) in ASSET_SPECS.items():
        asset_uris[token_name] = encode_png_asset(RAW_DIR / filename, max_size)

    username = os.environ.get("GITHUB_USERNAME", "asimansari-git")
    token = os.environ.get("GITHUB_TOKEN", "")
    stats = fetch_github_stats(username, token)

    replacements = {**asset_uris, **stats}

    templates = sorted(TEMPLATE_DIR.glob("*.svg"))
    if not templates:
        raise RuntimeError(f"No SVG templates found in {TEMPLATE_DIR}")

    for tpl_path in templates:
        svg_text = tpl_path.read_text(encoding="utf-8")
        for key, value in replacements.items():
            svg_text = svg_text.replace(f"{{{{{key}}}}}", value)

        # Safety check: verify zero unresolved tokens & zero external image URLs
        leftover = re.findall(r"\{\{[A-Z0-9_]+\}\}", svg_text)
        if leftover:
            raise ValueError(f"Unresolved template placeholders in {tpl_path.name}: {leftover}")

        ext_imgs = re.findall(r'<image[^>]+href="https?://', svg_text)
        if ext_imgs:
            raise ValueError(f"Forbidden external image URL detected in {tpl_path.name}")

        out_path = OUT_DIR / tpl_path.name
        out_path.write_text(svg_text, encoding="utf-8")
        size_kb = out_path.stat().st_size / 1024.0
        print(f"  [ok] {out_path.relative_to(REPO_ROOT)} ({size_kb:.1f} KB)")

    print(f"Built {len(templates)} GitHub-safe animated SVGs.")


if __name__ == "__main__":
    build_all()
