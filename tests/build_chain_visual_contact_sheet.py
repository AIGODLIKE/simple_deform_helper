"""Build a manifest and contact sheet for captured SDH viewport evidence."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--visual-dir", type=Path, required=True)
    parser.add_argument("--output-prefix", type=Path, required=True)
    return parser.parse_args()


def status_for(image_path):
    result_path = image_path.with_suffix(".result.txt")
    if not result_path.exists():
        return "MISSING_RESULT"
    first_line = result_path.read_text(encoding="utf-8").splitlines()
    return first_line[0].strip() if first_line else "EMPTY_RESULT"


def record_for(image_path, visual_dir):
    name = image_path.stem
    kind = "chain" if "CHAIN" in name else "cage" if "CAGE" in name else "other"
    return {
        "case_id": name,
        "kind": kind,
        "status": status_for(image_path),
        "screenshot": str(image_path.relative_to(visual_dir)).replace("\\", "/"),
        "width": Image.open(image_path).width,
        "height": Image.open(image_path).height,
        "bytes": image_path.stat().st_size,
    }


def build_contact_sheet(images, output, tile_width=480, tile_height=360):
    columns = 2
    rows = (len(images) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * tile_width, rows * tile_height), "#202124")
    draw = ImageDraw.Draw(sheet)
    for index, image_path in enumerate(images):
        image = Image.open(image_path).convert("RGB")
        tile = ImageOps.contain(image, (tile_width - 20, tile_height - 58))
        left = (index % columns) * tile_width
        top = (index // columns) * tile_height
        x = left + (tile_width - tile.width) // 2
        y = top + 8
        sheet.paste(tile, (x, y))
        draw.text((left + 10, top + tile_height - 42), image_path.stem[:70], fill="white")
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)


def main():
    args = parse_args()
    visual_dir = args.visual_dir.resolve()
    prefix = args.output_prefix.resolve()
    images = tuple(sorted(
        path for path in visual_dir.glob("*.png")
        if path.name != prefix.with_suffix(".png").name
    ))
    records = [record_for(path, visual_dir) for path in images]
    manifest = {
        "schema_version": 1,
        "visual_directory": str(visual_dir),
        "screenshot_count": len(records),
        "records": records,
    }
    prefix.parent.mkdir(parents=True, exist_ok=True)
    prefix.with_suffix(".json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with prefix.with_suffix(".csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(records[0]) if records else (
            "case_id", "kind", "status", "screenshot", "width", "height", "bytes"))
        writer.writeheader()
        writer.writerows(records)
    build_contact_sheet(images, prefix.with_suffix(".png"))
    print(json.dumps({"screenshot_count": len(records), "output_prefix": str(prefix)}))


if __name__ == "__main__":
    main()
