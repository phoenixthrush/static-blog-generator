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

## sample journal

The fictional sample posts and assets are kept in `examples/content/`.
Preview them without adding anything to your own `content/` folder:

```bash
python -m pip install -r requirements.txt
python build.py --demo
python -m http.server 8000 --directory dist
```

Open [localhost:8000](http://localhost:8000). The demo includes an SVG postcard,
a short generated WAV arpeggio, and a text attachment. Demo builds bundle their
media in `dist/media/`; regular builds use your separately served media directory.

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
