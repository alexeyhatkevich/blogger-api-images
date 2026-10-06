"""Image handling for a Markdown -> Blogger publisher. Pure functions, no network.

Blogger API v3 has no media upload endpoint, and Blogger does not render
<img src="data:..."> (the post shows a grey "IMG" box). Images have to live on
Blogger's own CDN, which only the web editor's upload produces. So:

1. `render_fixed` turns every local image without a hosted URL into a visible
   marker "[UPLOAD IMAGE HERE: file.png]" at its position.
2. A human uploads the image in the Blogger editor at the marker and deletes it.
3. `adopt` reads the post HTML back, pairs the new hosted <img> URLs with the
   still-pending local images in document order, and returns the updated map
   (stored as hosted-images.json).
4. Every later render swaps local paths for their hosted URLs, so republishing
   from Markdown never wipes the uploaded images.
"""

import base64
import html
import mimetypes
import re

UPLOAD_MARK = "UPLOAD IMAGE HERE:"
IMG_TAG = re.compile(r'<img src="([^"]+)"([^>]*)>')
REMOTE = re.compile(r"(?i)^(https?:|data:)")


class MarkersRemainError(Exception):
    """The post still contains upload markers: some images were not uploaded yet."""


class CountMismatchError(Exception):
    """Number of new hosted images differs from the number of pending local images."""

    def __init__(self, found, pending):
        self.found, self.pending = found, pending
        super().__init__(
            f"Found {found} new hosted image(s) in the post "
            f"but {len(pending)} pending local image(s): {pending}"
        )


def md_to_html(src):
    """Tiny Markdown subset: '#' headings, paragraphs and ![alt](src) images."""
    blocks = [b.strip() for b in re.split(r"\n\s*\n", src) if b.strip()]
    out = []
    for block in blocks:
        text = html.escape(block, quote=False)
        text = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)\)", r'<img src="\2" alt="\1">', text)
        if m := re.match(r"(#{1,6})\s+(.*)", text):
            n = len(m.group(1))
            out.append(f"<h{n}>{m.group(2)}</h{n}>")
        else:
            out.append(f"<p>{text}</p>")
    return "\n".join(out)


def local_images(content):
    """Local (non-http, non-data) image sources in document order."""
    srcs = (html.unescape(s) for s, _ in IMG_TAG.findall(content))
    return [s for s in srcs if not REMOTE.match(s)]


def render_naive(content, read_bytes):
    """The broken approach: inline every local image as a base64 data: URI.

    The API accepts and stores it, but Blogger renders a grey "IMG" box."""
    def repl(m):
        src = html.unescape(m.group(1))
        if REMOTE.match(src):
            return m.group(0)
        mime = mimetypes.guess_type(src)[0] or "application/octet-stream"
        data = base64.b64encode(read_bytes(src)).decode("ascii")
        return f'<img src="data:{mime};base64,{data}"{m.group(2)}>'
    return IMG_TAG.sub(repl, content)


def render_fixed(content, hosted):
    """Swap local images for hosted URLs; images not uploaded yet become a marker."""
    def repl(m):
        src = html.unescape(m.group(1))
        if REMOTE.match(src):
            return m.group(0)
        if src in hosted:
            return f'<img style="max-width:100%;height:auto" src="{html.escape(hosted[src])}"{m.group(2)}>'
        name = html.escape(src.rsplit("/", 1)[-1])
        return f"<b>[{UPLOAD_MARK} {name}]</b>"
    return IMG_TAG.sub(repl, content)


def hosted_images(post_html):
    """http(s) <img src> URLs of the post as Blogger returns it, in document order."""
    urls = re.findall(r'<img\b[^>]*?\bsrc="(https?://[^"]+)"', post_html)
    return [html.unescape(u) for u in urls]


def adopt(local_html, post_html, hosted):
    """Return a new local->hosted map after the images were uploaded in the editor.

    local_html: our rendering of the Markdown (with local image paths)
    post_html:  the post content fetched with view=ADMIN
    hosted:     the current map (not modified)
    """
    if UPLOAD_MARK in post_html:
        raise MarkersRemainError(
            f"Post still has '{UPLOAD_MARK}' markers - upload those images in the editor first."
        )
    pending = [s for s in local_images(local_html) if s not in hosted]
    known = set(hosted.values())
    new = [u for u in hosted_images(post_html) if u not in known]
    if len(new) != len(pending):
        raise CountMismatchError(len(new), pending)
    result = dict(hosted)
    result.update(zip(pending, new))
    return result


def original_size(url):
    """Editor URLs carry a display size segment like /w548-h167/; /s1600/ gives the original."""
    return re.sub(r"/(?:w\d+-h\d+|s\d+|w\d+|h\d+)(?:-[a-z]+)?/(?=[^/]+$)", "/s1600/", url)
