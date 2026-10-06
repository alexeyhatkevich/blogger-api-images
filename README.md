# blogger-api-images

Getting images into Blogger posts that you publish from Markdown through the
**Blogger API v3**.

## The problem

A Markdown-to-HTML publisher inlines local images as
`<img src="data:image/png;base64,...">` and sends the post with `posts.insert` /
`posts.patch`. The API accepts it, and reading the post back with `view=ADMIN`
returns the `data:` URI intact (a 250 KB inline image is stored just fine). But the
rendered post shows a grey square with the text "IMG" where the picture should be,
with the caption underneath.

## Why

- Blogger API v3 has **no image/media upload endpoint**.
- Blogger **does not render `data:` URI images**.
- The images Blogger renders live on its own CDN
  (`https://blogger.googleusercontent.com/img/b/...`), and the only way to get a
  file there is the upload in the web editor.

## The fix

A small human-in-the-loop flow (see [`blogger_images/images.py`](blogger_images/images.py)):

1. **Render with markers.** Each local image that has no hosted URL yet becomes a
   visible bold marker `[UPLOAD IMAGE HERE: file.png]` at its position. No `data:` URIs.
2. **Upload by hand.** In the Blogger editor, put the cursor on the marker,
   *Insert image* -> **Upload from computer** (or drag the file in), then delete the
   marker. (The "Photos"/album option only says "No albums found".)
3. **Adopt.** `adopt` fetches the post (`view=ADMIN`), refuses while any marker
   remains, collects the `http(s)` `<img src>` URLs it does not know yet, pairs them
   **in document order** with the still-pending local images and writes
   `hosted-images.json` (keep it out of git):
   `{"post-images/x.png": "https://blogger.googleusercontent.com/..."}`.
   A count mismatch is an error that lists the pending files.
4. **Republish safely.** Every later render swaps local paths for their hosted
   URLs, so updating the post from Markdown never wipes the uploaded images.

Hosted URLs carry an editor-chosen display size segment such as `/w548-h167/`;
`/s1600/` in that position serves the original size (`original_size()`).

## How to run

Python 3.10+, standard library only.

```bash
git clone https://github.com/alexeyhatkevich/blogger-api-images
cd blogger-api-images

# tests (no network)
python3 -m unittest -v

# see the naive vs fixed HTML for the example post
python3 -m blogger_images render example/post.md --naive | head -c 400
python3 -m blogger_images render example/post.md

# after uploading in the editor: record hosted URLs
python3 -m blogger_images adopt example/post.md --post-html saved-post.html
# or fetch the post from the API directly
BLOGGER_BLOG_ID=... BLOGGER_ACCESS_TOKEN=... python3 -m blogger_images adopt example/post.md --post-id <id>
```

## Tests

| Test | Proves |
| --- | --- |
| `test_naive_inlines_image_as_data_uri` | the naive publisher embeds bytes Blogger will not render |
| `test_fixed_emits_visible_marker_for_each_unuploaded_image` | markers appear in place of not-yet-hosted images |
| `test_fixed_uses_hosted_url_when_known` | republishing keeps uploaded images |
| `test_adopt_pairs_hosted_urls_with_pending_images_in_document_order` | pairing is positional |
| `test_adopt_refuses_while_markers_remain` | no guessing while an upload is missing |
| `test_adopt_reports_count_mismatch_with_pending_files` | a deleted-but-not-uploaded marker is caught |
| `test_cli_adopt_then_render_round_trip` | the whole flow works end to end, offline |

## License

MIT

Write-up: https://alexeyhatkevich.blogspot.com
