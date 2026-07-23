"""Resolve the newest official Blender daily build for CI."""

import json
import sys
from urllib.request import urlopen


with urlopen("https://builder.blender.org/download/daily/?v=2&format=json") as response:
    builds = json.load(response)

candidates = [
    build for build in builds
    if build.get("platform") == "linux"
    and build.get("architecture") == "x86_64"
    and build.get("file_extension") == "xz"
    and build.get("branch") == "main"
    and build.get("release_cycle") in {"alpha", "beta", "candidate"}
]
if not candidates:
    raise SystemExit("No Linux x86_64 Blender next build found")

newest = max(candidates, key=lambda build: (build["file_mtime"], build["version"]))
sys.stdout.write(newest["url"])
