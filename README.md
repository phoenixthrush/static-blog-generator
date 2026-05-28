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

## output

generated files go to `dist/`.
