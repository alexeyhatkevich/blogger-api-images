"""Minimal CLI around the pure functions in images.py.

  python3 -m blogger_images render  post.md [--naive]      print the HTML that would be sent
  python3 -m blogger_images adopt   post.md --post-html F  record hosted URLs from a saved post body
  python3 -m blogger_images adopt   post.md --post-id ID   same, fetching the post from Blogger API v3
                                                            (needs BLOGGER_BLOG_ID and BLOGGER_ACCESS_TOKEN)

The map is stored next to post.md as hosted-images.json (keep it out of git).
"""

import argparse
import json
import os
import sys
import urllib.request

from . import images

HOSTED = "hosted-images.json"


def load_hosted(base_dir):
    path = os.path.join(base_dir, HOSTED)
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def fetch_post_content(post_id):
    """GET the post as the editor saved it. view=ADMIN returns the raw stored content."""
    blog = os.environ["BLOGGER_BLOG_ID"]
    req = urllib.request.Request(
        f"https://www.googleapis.com/blogger/v3/blogs/{blog}/posts/{post_id}?view=ADMIN",
        headers={"Authorization": f"Bearer {os.environ['BLOGGER_ACCESS_TOKEN']}"},
    )
    with urllib.request.urlopen(req) as r:
        return json.load(r).get("content", "")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="blogger_images", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render")
    r.add_argument("file")
    r.add_argument("--naive", action="store_true", help="inline images as data: URIs (the broken way)")
    a = sub.add_parser("adopt")
    a.add_argument("file")
    src = a.add_mutually_exclusive_group(required=True)
    src.add_argument("--post-html", help="file with the post content as returned by the API")
    src.add_argument("--post-id")
    args = ap.parse_args(argv)

    base_dir = os.path.dirname(os.path.abspath(args.file))
    with open(args.file, encoding="utf-8") as f:
        local_html = images.md_to_html(f.read())
    hosted = load_hosted(base_dir)

    if args.cmd == "render":
        if args.naive:
            def read(p):
                with open(os.path.join(base_dir, p), "rb") as fh:
                    return fh.read()
            print(images.render_naive(local_html, read))
        else:
            print(images.render_fixed(local_html, hosted))
        return 0

    if args.post_html:
        with open(args.post_html, encoding="utf-8") as f:
            post_html = f.read()
    else:
        post_html = fetch_post_content(args.post_id)
    try:
        new_map = images.adopt(local_html, post_html, hosted)
    except (images.MarkersRemainError, images.CountMismatchError) as e:
        print(e, file=sys.stderr)
        return 1
    with open(os.path.join(base_dir, HOSTED), "w", encoding="utf-8") as f:
        json.dump(new_map, f, indent=2)
    for k in new_map.keys() - hosted.keys():
        print(f"{k} -> {new_map[k]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
