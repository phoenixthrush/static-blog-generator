# static blog generator

simple static blog generator for my journal.

## run

```bash
docker compose up --build
```

## content

put posts in `content/` like this:

```text
content/
├── XXXX-XX-XX/
│   ├── README.txt
│   ├── image.jpg
│   └── audio.m4a
```

`README.md` or `README.txt` inside a post folder becomes the post text.

other files are shown as assets.

## video previews

The build uses FFmpeg to extract the first frame of each video into
`dist/thumbnails/`. The player displays that JPEG before loading the video.
Builds reuse existing posters for videos with the same path, size, and
modification time and remove posters for videos absent from the build.
Delete `dist/thumbnails/` before rebuilding to regenerate all posters.

The Docker image includes FFmpeg. For a local Python build, install `ffmpeg`
and make sure it is on your PATH. If a poster cannot be generated, the build
warns and still includes the video.

## open locally

To build a portable copy, run either command:

```bash
python build.py --bundle-media
docker compose run --build --rm site-builder python build.py --bundle-media
```

Open `dist/index.html` directly in your browser. This copies post assets
into `dist/media/` so their relative links work from disk or over HTTP.
Keep the whole `dist/` folder together when moving the bundle.

Regular builds keep the site and thumbnails in `dist/`. The post asset
links still resolve to `/media/` when the blog is hosted at the site root,
so your existing media server can serve the originals separately.

## sample journal

The fictional sample posts and assets are kept in `examples/content/`.
Preview them without adding anything to your own `content/` folder:

```bash
python -m pip install -r requirements.txt
python build.py --demo
python -m http.server 8000 --directory dist
```

Open [localhost:8000](http://localhost:8000) or open `dist/index.html` directly.
The demo includes an SVG postcard, a short generated WAV arpeggio, and a text
attachment. Demo builds bundle their media in `dist/media/`.

## fonts

The [Playpen Sans](https://github.com/TypeTogether/Playpen-Sans) font is bundled
under `static/fonts/playpen-sans/`, including its SIL Open Font License. The
builder copies it to `dist/fonts/playpen-sans/` alongside the stylesheet.
Font files are served from your own server, with no CDN or external font service.

## archive

The sidebar groups entries by year, then month, newest first. Each year and
month can be expanded independently and shows its page count. The current
entry's year and month open automatically; the home page opens the latest ones.
The entry arrows intentionally go left to older entries and right to newer ones
(including the arrow-key and H/L shortcuts).

## output

generated files go to `dist/`.

## checks

```bash
python -m pip install ruff
ruff format .
ruff check .
```
