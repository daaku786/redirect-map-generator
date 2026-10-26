#!/usr/bin/env python3
"""Build a 301 redirect map for a site migration or URL restructure.

Give it the old URLs and the new URLs (sitemap URL, sitemap file, or a text/CSV
list). For every old URL that no longer exists, it finds the best new match by
slug and path similarity, and falls back to the closest parent folder or the
home page. Low confidence matches are flagged for a human to review.

Output: CSV for review, plus ready to paste .htaccess, Nginx, Netlify/Cloudflare
Pages _redirects, Vercel JSON, or a WordPress Redirection plugin CSV.

No third-party dependencies. Python 3.8+.
"""

import argparse
import csv
import gzip
import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher

__version__ = "1.0.0"
UA = f"redirect-map-generator/{__version__} (+https://github.com/daaku786/redirect-map-generator)"
SM_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
STOP_WORDS = {"a", "an", "and", "the", "of", "for", "to", "in", "on", "with", "html", "htm", "php", "aspx", "index"}


# ------------------------------------------------------------------ loading

def _read_source(src):
    if src.startswith(("http://", "https://")):
        req = urllib.request.Request(src, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
    else:
        with open(src, "rb") as f:
            data = f.read()
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return data


def load_urls(src, seen=None):
    """Return a list of URLs or paths from a sitemap (index), .txt or .csv source."""
    seen = seen if seen is not None else set()
    if src in seen:
        return []
    seen.add(src)
    data = _read_source(src)
    head = data[:500].lstrip()
    if head.startswith(b"<?xml") or b"<urlset" in head or b"<sitemapindex" in head:
        root = ET.fromstring(data)
        locs = [l.text.strip() for l in root.iter(SM_NS + "loc") if l.text]
        if root.tag.endswith("sitemapindex"):
            out = []
            for child in locs:
                out += load_urls(child, seen)
            return out
        return locs
    text = data.decode("utf-8-sig", "replace")
    urls = []
    for row in csv.reader(text.splitlines()):
        if not row:
            continue
        cell = row[0].strip()
        if cell and not cell.startswith("#") and (cell.startswith("/") or "://" in cell):
            urls.append(cell)
    return urls


def norm_path(url):
    """Path only, lowercased, without trailing slash (except root), no query."""
    p = urllib.parse.urlsplit(url if "://" in url else "http://x" + (url if url.startswith("/") else "/" + url))
    path = urllib.parse.unquote(p.path).lower()
    path = re.sub(r"/+", "/", path)
    path = re.sub(r"/index\.(html?|php)$", "/", path)
    if len(path) > 1:
        path = path.rstrip("/")
    return path or "/"


def tokens(path):
    words = re.split(r"[^a-z0-9]+", path.lower())
    return [w for w in words if w and w not in STOP_WORDS]


def slug(path):
    last = path.rstrip("/").rsplit("/", 1)[-1]
    return re.sub(r"\.(html?|php|aspx)$", "", last)


# ------------------------------------------------------------------ matching

def _stem(word):
    return word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word


def score(old_path, new_path):
    """0..1 similarity: slug similarity, word overlap and full path similarity.

    The new side is compared both by its last segment and by its last two segments,
    so /water-heater-installation matches /water-heaters/installation/.
    """
    s_old = slug(old_path)
    parts = [p for p in new_path.strip("/").split("/") if p]
    candidates = [slug(new_path)] + (["-".join(parts[-2:])] if len(parts) > 1 else [])
    slug_ratio = max((SequenceMatcher(None, s_old, c).ratio() for c in candidates if c and s_old), default=0.0)
    t_old = {_stem(t) for t in tokens(s_old)}
    t_new = {_stem(t) for t in tokens("-".join(parts[-2:]))}
    overlap = len(t_old & t_new) / len(t_old | t_new) if t_old | t_new else 0.0
    path_ratio = SequenceMatcher(None, old_path, new_path).ratio()
    return round(0.45 * slug_ratio + 0.4 * overlap + 0.15 * path_ratio, 3)


def build_map(old_urls, new_urls, threshold=0.6, review_below=0.75):
    new_by_path = {}
    for u in new_urls:
        new_by_path.setdefault(norm_path(u), u)
    new_paths = list(new_by_path)

    rows = []
    for old in dict.fromkeys(old_urls):
        op = norm_path(old)
        if op in new_by_path:
            continue  # unchanged URL, no redirect needed
        best, best_score = None, 0.0
        for np_ in new_paths:
            sc = score(op, np_)
            if sc > best_score:
                best, best_score = np_, sc
        if best and best_score >= threshold:
            method = "match"
            target = best
        else:
            # fall back to the deepest existing parent folder, then home
            target, method, best_score = "/", "home", 0.0
            parts = op.strip("/").split("/")[:-1]
            while parts:
                parent = "/" + "/".join(parts)
                if parent in new_by_path:
                    target, method = parent, "parent"
                    break
                parts.pop()
        review = method != "match" or best_score < review_below
        rows.append({
            "old": old,
            "old_path": op,
            "new": new_by_path.get(target, target),
            "new_path": target,
            "score": best_score,
            "method": method,
            "review": "yes" if review else "",
        })
    return rows


# ------------------------------------------------------------------ output

def _src_path(row, keep_trailing_slash):
    p = urllib.parse.urlsplit(row["old"] if "://" in row["old"] else "http://x" + row["old"]).path or "/"
    return p if keep_trailing_slash else (p.rstrip("/") or "/")


def _dest(row, absolute):
    return row["new"] if absolute and "://" in row["new"] else urllib.parse.urlsplit(
        row["new"] if "://" in row["new"] else "http://x" + row["new"]).path or "/"


def render(rows, fmt, absolute=False):
    if fmt == "htaccess":
        lines = ["# 301 redirects generated by redirect-map-generator", "RewriteEngine On"]
        for r in rows:
            src = re.escape(_src_path(r, False).lstrip("/"))
            lines.append(f"RewriteRule ^{src}/?$ {_dest(r, absolute)} [R=301,L]")
        return "\n".join(lines) + "\n"
    if fmt == "nginx":
        lines = ["# 301 redirects generated by redirect-map-generator (put inside your server {} block)"]
        for r in rows:
            src = _src_path(r, False)
            if src == "/":
                continue
            lines.append(f"location ~* ^{re.escape(src)}/?$ {{ return 301 {_dest(r, absolute)}; }}")
        return "\n".join(lines) + "\n"
    if fmt == "netlify":
        return "\n".join(f"{_src_path(r, True)}  {_dest(r, absolute)}  301" for r in rows) + "\n"
    if fmt == "vercel":
        return json.dumps({"redirects": [
            {"source": _src_path(r, False), "destination": _dest(r, absolute), "permanent": True}
            for r in rows]}, indent=2) + "\n"
    if fmt == "wordpress":
        # Redirection plugin CSV import: source, target, regex, code
        out = ["source,target,regex,code"]
        for r in rows:
            out.append(f"{_src_path(r, True)},{_dest(r, absolute)},0,301")
        return "\n".join(out) + "\n"
    raise ValueError(fmt)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build a 301 redirect map from old and new URL lists.")
    ap.add_argument("old", help="old URLs: sitemap URL, sitemap .xml file, or .txt/.csv list")
    ap.add_argument("new", help="new URLs: same formats")
    ap.add_argument("-o", "--output", default="redirects.csv", help="review CSV (default redirects.csv, '-' for stdout)")
    ap.add_argument("--format", action="append", choices=["htaccess", "nginx", "netlify", "vercel", "wordpress"],
                    default=[], help="also write a server config, repeatable")
    ap.add_argument("--threshold", type=float, default=0.6, help="min score to accept a match (default 0.6)")
    ap.add_argument("--review-below", type=float, default=0.75, help="flag matches below this score (default 0.75)")
    ap.add_argument("--absolute", action="store_true", help="use full new URLs (for cross domain moves)")
    ap.add_argument("--version", action="version", version=__version__)
    args = ap.parse_args(argv)

    old_urls, new_urls = load_urls(args.old), load_urls(args.new)
    print(f"Old URLs: {len(old_urls)}   New URLs: {len(new_urls)}", file=sys.stderr)
    rows = build_map(old_urls, new_urls, args.threshold, args.review_below)

    fields = ["old", "new", "score", "method", "review"]
    f = sys.stdout if args.output == "-" else open(args.output, "w", newline="", encoding="utf-8")
    try:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    finally:
        if f is not sys.stdout:
            f.close()

    ext = {"htaccess": ".htaccess", "nginx": "redirects.nginx.conf", "netlify": "_redirects",
           "vercel": "vercel.redirects.json", "wordpress": "redirection-import.csv"}
    for fmt in args.format:
        with open(ext[fmt], "w", encoding="utf-8") as out:
            out.write(render(rows, fmt, args.absolute))
        print(f"Wrote {ext[fmt]}", file=sys.stderr)

    matched = sum(r["method"] == "match" for r in rows)
    review = sum(bool(r["review"]) for r in rows)
    print(f"{len(rows)} redirects: {matched} matched, {len(rows) - matched} parent/home fallbacks, "
          f"{review} flagged for review", file=sys.stderr)
    if args.output != "-":
        print(f"Wrote {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
