#!/usr/bin/env python3
"""Verify portable config digests and revision labels in a docker-save bundle."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tarfile
from pathlib import Path

DIGEST_RE = re.compile(r"^sha256:([0-9a-f]{64})$")
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")


def _parse_image(value: str) -> tuple[str, str]:
    name, separator, digest = value.partition("=")
    if not separator or not name or DIGEST_RE.fullmatch(digest) is None:
        raise argparse.ArgumentTypeError("image must be NAME=sha256:<64 lowercase hex>")
    return name, digest


def verify_bundle(bundle: Path, revision: str, expected: list[tuple[str, str]]) -> None:
    if not bundle.is_file() or bundle.is_symlink():
        raise ValueError("bundle is missing or symlinked")
    if REVISION_RE.fullmatch(revision) is None:
        raise ValueError("revision must be a 40-character lowercase Git SHA")
    with tarfile.open(bundle, "r") as archive:
        manifest_file = archive.extractfile("manifest.json")
        if manifest_file is None:
            raise ValueError("bundle manifest.json missing")
        manifest = json.load(manifest_file)
        if not isinstance(manifest, list):
            raise ValueError("bundle manifest is not a list")
        by_tag: dict[str, dict[str, object]] = {}
        for item in manifest:
            if not isinstance(item, dict):
                raise ValueError("bundle manifest entry is invalid")
            for tag in item.get("RepoTags") or []:
                if not isinstance(tag, str) or tag in by_tag:
                    raise ValueError("bundle repository tags are invalid or duplicated")
                by_tag[tag] = item
        for image_name, expected_digest in expected:
            tag = image_name if ":" in image_name.rsplit("/", 1)[-1] else f"{image_name}:latest"
            item = by_tag.get(tag)
            if item is None:
                raise ValueError(f"bundle image missing: {tag}")
            digest_match = DIGEST_RE.fullmatch(expected_digest)
            assert digest_match is not None
            expected_hex = digest_match.group(1)
            config_name = str(item.get("Config") or "")
            if config_name not in {f"blobs/sha256/{expected_hex}", f"{expected_hex}.json"}:
                raise ValueError(f"bundle config digest mismatch: {tag}")
            config_file = archive.extractfile(config_name)
            if config_file is None:
                raise ValueError(f"bundle config missing: {tag}")
            config_bytes = config_file.read()
            if hashlib.sha256(config_bytes).hexdigest() != expected_hex:
                raise ValueError(f"bundle config content hash mismatch: {tag}")
            config = json.loads(config_bytes)
            labels = (config.get("config") or {}).get("Labels") or {}
            if labels.get("org.opencontainers.image.revision") != revision:
                raise ValueError(f"bundle revision mismatch: {tag}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--image", action="append", required=True, type=_parse_image)
    args = parser.parse_args()
    try:
        verify_bundle(args.bundle, args.revision, args.image)
    except (OSError, tarfile.TarError, json.JSONDecodeError, ValueError) as error:
        print(f"bundle_verification=FAIL reason={error}")
        return 2
    print(f"bundle_verification=PASS images={len(args.image)} revision={args.revision}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
