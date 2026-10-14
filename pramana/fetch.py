"""Download the openly licensed sources named in a course manifest."""
from __future__ import annotations

import html
import re
import shutil
import time
from pathlib import Path

import httpx
import yaml

from .config import settings

USER_AGENT = "Mozilla/5.0 (compatible; pramana-course-fetch/0.1)"


def load_manifest(course_id: str) -> dict:
    path = settings.course_dir / course_id / "course.yaml"
    return yaml.safe_load(path.read_text())


def _resolve(client: httpx.Client, url: str) -> str:
    """Digital Commons landing pages link to the file through a `viewcontent` URL."""
    if "digitalcommons." not in url:
        return url
    page = client.get(url).text
    match = re.search(r'href="([^"]+/viewcontent[^"]*)"', page)
    if not match:
        raise RuntimeError(f"no download link found on {url}")
    return html.unescape(match.group(1))


def _mirrors(client: httpx.Client, url: str) -> list[str]:
    """Other hosts for an archive.org file. Its download redirect sometimes lands on a mirror
    that answers 500 for one file while the item's other data node serves it fine."""
    match = re.match(r"https://archive\.org/download/([^/]+)/(.+)", url)
    if not match:
        return []
    try:
        meta = client.get(f"https://archive.org/metadata/{match.group(1)}").json()
    except (httpx.HTTPError, ValueError):
        return []
    return [f"https://{host}{meta['dir']}/{match.group(2)}" for host in (meta.get("d1"), meta.get("d2")) if host and meta.get("dir")]


def fetch_course(course_id: str, only: set[str] | None = None) -> list[Path]:
    manifest = load_manifest(course_id)
    out_dir = settings.raw_dir / course_id
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    with httpx.Client(follow_redirects=True, timeout=120, headers={"User-Agent": USER_AGENT}) as client:
        for source in manifest["sources"]:
            if only and source["id"] not in only:
                continue
            target = out_dir / source["file"]
            paths.append(target)
            if target.exists() and target.stat().st_size > 0:
                print(f"have   {source['id']:12s} {target.name}")
                continue
            shipped = settings.course_dir / course_id / "files" / source["file"]
            if shipped.exists():  # a source whose licence allows it and whose host blocks scripted downloads
                shutil.copyfile(shipped, target)
                print(f"copied {source['id']:12s} {target.name} (shipped with the repository)")
                continue
            partial = target.with_suffix(target.suffix + ".part")
            candidates = [source["url"]]
            for attempt in range(6):  # archive.org mirrors answer 5xx now and then
                try:
                    url = _resolve(client, candidates[attempt % len(candidates)])
                    with client.stream("GET", url) as response:
                        response.raise_for_status()
                        with partial.open("wb") as handle:
                            for block in response.iter_bytes(1 << 20):
                                handle.write(block)
                    partial.rename(target)
                    print(f"fetched {source['id']:12s} {target.name} ({target.stat().st_size / 1e6:.1f} MB)")
                    break
                except httpx.HTTPError as error:
                    print(f"retry  {source['id']:12s} attempt {attempt + 1}: {type(error).__name__}")
                    if len(candidates) == 1:
                        candidates.extend(_mirrors(client, source["url"]))
                    time.sleep(2 * (attempt + 1))
            else:
                print(f"FAILED {source['id']:12s} {source['url']}")
    return paths
