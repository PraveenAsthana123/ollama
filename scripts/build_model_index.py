#!/usr/bin/env python3
"""Merge Ollama manifest catalogs while linking, never copying, model blobs."""

import argparse
import shutil
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    parser.add_argument("sources", nargs="+", type=Path)
    args = parser.parse_args()
    manifests = args.destination / "manifests"
    blobs = args.destination / "blobs"
    manifests.mkdir(parents=True, exist_ok=True)
    blobs.mkdir(parents=True, exist_ok=True)
    # Later sources replace duplicate manifests; blobs are content-addressed.
    for source in args.sources:
        for blob in (source / "blobs").iterdir():
            target = blobs / blob.name
            if blob.is_file() and not target.exists():
                target.symlink_to(blob.resolve())
        for manifest in (source / "manifests").rglob("*"):
            if not manifest.is_file():
                continue
            target = manifests / manifest.relative_to(source / "manifests")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(manifest, target)
    print(sum(path.is_file() for path in manifests.rglob("*")), "model tags indexed")


if __name__ == "__main__":
    main()
