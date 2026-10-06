import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

from blogger_images import (
    UPLOAD_MARK,
    CountMismatchError,
    MarkersRemainError,
    adopt,
    local_images,
    md_to_html,
    original_size,
    render_fixed,
    render_naive,
)
from blogger_images.__main__ import main

CDN = "https://blogger.googleusercontent.com/img/b/AAAA/BBBB"
MD = """# Post

Intro text.

![First](post-images/first.png)

*caption one*

Middle text.

![Second](post-images/second.png)
"""
PNG = b"\x89PNG\r\n\x1a\nfake"


def editor_saved(*urls, extra=""):
    """Post content the way the editor stores it after uploads: <a><img ... src=...></a>."""
    imgs = "".join(
        f'<div class="separator"><a href="{u}"><img border="0" data-original-height="300" '
        f'src="{u}" width="548" /></a></div>'
        for u in urls
    )
    return f"<h1>Post</h1><p>Intro text.</p>{imgs}{extra}"


class NaiveTests(unittest.TestCase):
    def test_naive_inlines_image_as_data_uri(self):
        # Proves the naive publisher embeds the bytes: the API stores this, Blogger shows a grey "IMG" box.
        out = render_naive(md_to_html(MD), lambda p: PNG)
        self.assertIn('src="data:image/png;base64,', out)
        self.assertEqual(local_images(out), [])  # nothing left to upload - and nothing hosted either

    def test_naive_output_contains_no_hosted_url(self):
        # Proves no image in the naive output points at Blogger's CDN, which is the only thing Blogger renders.
        out = render_naive(md_to_html(MD), lambda p: PNG)
        self.assertNotIn("googleusercontent", out)


class FixedRenderTests(unittest.TestCase):
    def test_fixed_emits_visible_marker_for_each_unuploaded_image(self):
        # Proves every local image without a hosted URL becomes a bold marker at its position.
        out = render_fixed(md_to_html(MD), {})
        self.assertIn(f"<b>[{UPLOAD_MARK} first.png]</b>", out)
        self.assertIn(f"<b>[{UPLOAD_MARK} second.png]</b>", out)
        self.assertLess(out.index("first.png"), out.index("second.png"))
        self.assertNotIn("<img", out)
        self.assertNotIn("data:", out)

    def test_fixed_uses_hosted_url_when_known(self):
        # Proves republishing from Markdown keeps the uploaded image instead of wiping it.
        hosted = {"post-images/first.png": f"{CDN}/w548-h167/first.png"}
        out = render_fixed(md_to_html(MD), hosted)
        self.assertIn(f'src="{CDN}/w548-h167/first.png"', out)
        self.assertIn(f"[{UPLOAD_MARK} second.png]", out)
        self.assertNotIn("first.png]", out)

    def test_fixed_leaves_remote_images_alone(self):
        # Proves images that already point at a URL pass through unchanged.
        src = md_to_html("![x](https://example.com/a.png)")
        self.assertEqual(render_fixed(src, {}), src)


class AdoptTests(unittest.TestCase):
    def setUp(self):
        self.local = md_to_html(MD)

    def test_adopt_pairs_hosted_urls_with_pending_images_in_document_order(self):
        # Proves the first uploaded image maps to the first pending local image, the second to the second.
        post = editor_saved(f"{CDN}/w548-h167/a.png", f"{CDN}/w400-h300/b.png")
        result = adopt(self.local, post, {})
        self.assertEqual(result, {
            "post-images/first.png": f"{CDN}/w548-h167/a.png",
            "post-images/second.png": f"{CDN}/w400-h300/b.png",
        })

    def test_adopt_skips_already_mapped_images(self):
        # Proves a second adopt round only pairs the images that were still pending.
        known = f"{CDN}/w548-h167/a.png"
        hosted = {"post-images/first.png": known}
        post = editor_saved(known, f"{CDN}/w400-h300/b.png")
        result = adopt(self.local, post, hosted)
        self.assertEqual(result["post-images/second.png"], f"{CDN}/w400-h300/b.png")
        self.assertEqual(result["post-images/first.png"], known)

    def test_adopt_does_not_mutate_input_map(self):
        # Proves the caller's map is only replaced when adopt succeeds.
        hosted = {}
        adopt(self.local, editor_saved(f"{CDN}/s1600/a.png", f"{CDN}/s1600/b.png"), hosted)
        self.assertEqual(hosted, {})

    def test_adopt_refuses_while_markers_remain(self):
        # Proves adopt will not guess while a marker shows an image is still missing.
        post = editor_saved(f"{CDN}/s1600/a.png", extra=f"<b>[{UPLOAD_MARK} second.png]</b>")
        with self.assertRaises(MarkersRemainError):
            adopt(self.local, post, {})

    def test_adopt_reports_count_mismatch_with_pending_files(self):
        # Proves a mismatch (marker deleted without uploading) is an error that lists the pending files.
        post = editor_saved(f"{CDN}/s1600/a.png")
        with self.assertRaises(CountMismatchError) as ctx:
            adopt(self.local, post, {})
        self.assertEqual(ctx.exception.found, 1)
        self.assertEqual(ctx.exception.pending, ["post-images/first.png", "post-images/second.png"])
        self.assertIn("post-images/second.png", str(ctx.exception))


class UrlTests(unittest.TestCase):
    def test_original_size_replaces_display_size_segment(self):
        # Proves /w548-h167/ (editor display size) can be swapped for /s1600/ (original size).
        self.assertEqual(original_size(f"{CDN}/w548-h167/a.png"), f"{CDN}/s1600/a.png")
        self.assertEqual(original_size(f"{CDN}/s320/a.png"), f"{CDN}/s1600/a.png")


class CliTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.md = os.path.join(self.dir, "post.md")
        with open(self.md, "w") as f:
            f.write(MD)

    def run_cli(self, *args):
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_cli_adopt_then_render_round_trip(self):
        # Proves the full flow offline: render markers -> adopt saved post -> render hosted URLs.
        code, out, _ = self.run_cli("render", self.md)
        self.assertEqual(code, 0)
        self.assertEqual(out.count(UPLOAD_MARK), 2)

        saved = os.path.join(self.dir, "saved.html")
        with open(saved, "w") as f:
            f.write(editor_saved(f"{CDN}/w548-h167/a.png", f"{CDN}/w548-h167/b.png"))
        code, _, _ = self.run_cli("adopt", self.md, "--post-html", saved)
        self.assertEqual(code, 0)
        with open(os.path.join(self.dir, "hosted-images.json")) as f:
            self.assertEqual(len(json.load(f)), 2)

        code, out, _ = self.run_cli("render", self.md)
        self.assertNotIn(UPLOAD_MARK, out)
        self.assertIn(f"{CDN}/w548-h167/b.png", out)

    def test_cli_adopt_fails_and_writes_nothing_on_mismatch(self):
        # Proves a failed adopt exits non-zero and leaves no half-written map behind.
        saved = os.path.join(self.dir, "saved.html")
        with open(saved, "w") as f:
            f.write(editor_saved(f"{CDN}/s1600/a.png"))
        code, _, err = self.run_cli("adopt", self.md, "--post-html", saved)
        self.assertEqual(code, 1)
        self.assertIn("pending", err)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "hosted-images.json")))


if __name__ == "__main__":
    unittest.main()
