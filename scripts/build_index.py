"""Build the disc_library index from TheDiscDB's data repository.

    git clone --depth 1 --filter=blob:none --sparse https://github.com/TheDiscDb/data.git discdb
    cd discdb && git sparse-checkout set --no-cone '/data/**/*-summary.txt' \
        '/data/**/metadata.json' '/data/**/tmdb.json'
    python3 scripts/build_index.py discdb data/index.json

One entry per main feature on each disc release (movies only):
  {"d": seconds, "c": chapters, "f": "uhd"|"bd"|"dvd", "id": tmdb id,
   "t": title, "y": year, "p": poster path, "b": backdrop path, "r": release slug}
Data: TheDiscDB (MIT licence), https://github.com/TheDiscDb/data
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def _secs(value: str) -> int:
    h, m, s = (int(x) for x in value.split(":"))
    return h * 3600 + m * 60 + s


def _format(release: str) -> str:
    slug = release.lower()
    if "4k" in slug or "uhd" in slug:
        return "uhd"
    if "dvd" in slug and "blu" not in slug:
        return "dvd"
    return "bd"


def build(repo: Path) -> list[dict]:
    entries = []
    for film_dir in sorted((repo / "data" / "movie").iterdir()):
        meta_file, tmdb_file = film_dir / "metadata.json", film_dir / "tmdb.json"
        if not meta_file.exists():
            continue
        meta = json.loads(meta_file.read_text())
        tmdb = json.loads(tmdb_file.read_text()) if tmdb_file.exists() else {}
        tmdb_id = (meta.get("ExternalIds") or {}).get("Tmdb") or tmdb.get("id")
        if not tmdb_id:
            continue
        film = {
            "id": int(tmdb_id),
            "t": meta.get("Title") or tmdb.get("title"),
            "y": meta.get("Year"),
            "p": tmdb.get("poster_path"),
            "b": tmdb.get("backdrop_path"),
        }
        for release_dir in sorted(p for p in film_dir.iterdir() if p.is_dir()):
            for summary in sorted(release_dir.glob("*-summary.txt")):
                for block in summary.read_text(errors="replace").split("\n\n"):
                    if not re.search(r"^Type: MainMovie", block, re.M):
                        continue
                    dur = re.search(r"^Duration: (\d+:\d+:\d+)", block, re.M)
                    chapters = re.search(r"^Chapters count: (\d+)", block, re.M)
                    if not dur:
                        continue
                    entries.append({
                        "d": _secs(dur[1]),
                        "c": int(chapters[1]) if chapters else None,
                        "f": _format(release_dir.name),
                        "r": release_dir.name,
                        **film,
                    })
    # one entry per (film, release, duration): multi-disc releases repeat the feature
    unique = {(e["id"], e["r"], e["d"]): e for e in entries}
    return sorted(unique.values(), key=lambda e: e["d"])


if __name__ == "__main__":
    repo, out = Path(sys.argv[1]), Path(sys.argv[2])
    index = build(repo)
    out.write_text(json.dumps({"source": "TheDiscDB (MIT), https://github.com/TheDiscDb/data",
                               "entries": index}, separators=(",", ":")))
    print(f"{len(index)} main features from {len({e['id'] for e in index})} films -> {out}")
