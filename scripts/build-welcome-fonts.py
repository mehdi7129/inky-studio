#!/usr/bin/env python3
"""Regenerate the welcome-only fonts from the pinned Noto source files.

Run with fonttools==4.60.1. The source directory uses the Google Fonts ofl/
layout. The generated provenance file records the exact upstream file URLs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from urllib.parse import quote

from fontTools import subset, version
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "server"))

from inky_web.welcome_locale import EXPIRED_COPY, FONT_DIR, WELCOME_COPY, welcome_font  # noqa: E402

COMMIT = "5026800714d07231937d92eb4cceabf06e05d74e"
SOURCE = f"https://raw.githubusercontent.com/google/fonts/{COMMIT}/ofl/"
FONTTOOLS_VERSION = "4.60.1"
CJK_LICENSE = "1c05c68c34f9708415aada51f17e1b0092d2cea709bf4a94cd38114f9e73d7d9"
SOURCES = {
    "ar": (
        "notosansarabic", "NotoSansArabic[wdth,wght].ttf",
        "63111b5b2e074dd48cc67692e0a2726d86ee94c1c37fe8598257b7b4e87e869e",
        "07fc70bfeb985cc1a87a8587d0a0c80bab11c86c9dc3fd95b6f0cb332f983e96",
    ),
    "ja": (
        "notosansjp", "NotoSansJP[wght].ttf",
        "c2f3b4d463500a2ddcd3849cded1fceeb9fd6d1c32e6cbecd568453ba50fc68f", CJK_LICENSE,
    ),
    "ko": (
        "notosanskr", "NotoSansKR[wght].ttf",
        "194018e6b2b293a7964f037b25c0249ce1418bc9ab3c971060a03aa57861e252", CJK_LICENSE,
    ),
    "zh-Hans": (
        "notosanssc", "NotoSansSC[wght].ttf",
        "a3041811a78c361b1de50f953c805e0244951c21c5bd412f7232ef0d899af0da", CJK_LICENSE,
    ),
    "zh-Hant": (
        "notosanstc", "NotoSansTC[wght].ttf",
        "864727d210d54f2537bbe23b3a839436c3992af72de9322af5270897246bd44f", CJK_LICENSE,
    ),
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_source(path: Path, expected: str) -> None:
    if digest(path) != expected:
        raise SystemExit(f"Unexpected SHA-256 for {path}")


def build_font(source: Path, language: str, bold: bool) -> dict:
    copy = WELCOME_COPY[language]
    lines = copy.headline + (EXPIRED_COPY[language],) if bold else copy.instructions + copy.compact
    destination = welcome_font(language, bold=bold)
    assert destination is not None

    with TTFont(source, recalcTimestamp=False) as font:
        axes = {axis.axisTag: axis.defaultValue for axis in font["fvar"].axes}
        axes["wght"] = 700 if bold else 400
        instantiateVariableFont(font, axes, inplace=True)
        options = subset.Options(name_IDs=["*"], layout_features=["*"])
        subsetter = subset.Subsetter(options=options)
        subsetter.populate(text=" ".join(lines))
        subsetter.subset(font)
        missing = set(map(ord, "".join(lines))) - font.getBestCmap().keys()
        if missing:
            raise SystemExit(f"Missing welcome glyphs for {language}: {missing!r}")

        # Preserve upstream copyright and licensing. Modified OFL derivatives
        # use distinct family names, including when upstream reserves "Source".
        family = f"Inky Welcome {language}"
        style = "Bold" if bold else "Regular"
        names = {1: family, 2: style, 3: destination.stem, 4: f"{family} {style}",
                 6: destination.stem, 16: family, 17: style, 21: family, 22: style, 25: destination.stem}
        for record in font["name"].names:
            if record.nameID in names:
                record.string = names[record.nameID].encode(record.getEncoding())
        font.save(destination)

    return {"file": destination.name, "sha256": digest(destination), "bytes": destination.stat().st_size}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", type=Path)
    args = parser.parse_args()
    if version != FONTTOOLS_VERSION:
        raise SystemExit(f"Use fonttools=={FONTTOOLS_VERSION} for reproducible output")
    if set(SOURCES) != {language for language, copy in WELCOME_COPY.items() if copy.subset}:
        raise SystemExit("Welcome font sources do not match the localized copy")

    result = {"fonttools_version": version, "licenses": "OFL-1.1", "sources": {}}
    for language, (family, name, font_hash, license_hash) in SOURCES.items():
        font = args.sources / family / name
        license_file = font.with_name("OFL.txt")
        check_source(font, font_hash)
        check_source(license_file, license_hash)
        license_destination = FONT_DIR / f"OFL-Welcome-{language}.txt"
        license_destination.write_bytes(license_file.read_bytes())
        result["sources"][language] = {
            "source": f"{SOURCE}{family}/{quote(name)}",
            "sha256": font_hash,
            "license_source": f"{SOURCE}{family}/OFL.txt",
            "license_sha256": license_hash,
            "license_file": license_destination.name,
            "subsets": [build_font(font, language, bold) for bold in (False, True)],
        }

    (FONT_DIR / "WELCOME-FONT-PROVENANCE.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8",
    )


if __name__ == "__main__":
    main()
