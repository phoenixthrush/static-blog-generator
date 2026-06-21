import shutil
from calendar import month_name
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import quote

import markdown
from bs4 import BeautifulSoup
from jinja2 import Environment, FileSystemLoader, select_autoescape

# -----------------------------
# Paths
# -----------------------------

root = Path(__file__).parent
content_dir = root / "content"
templates_dir = root / "templates"
static_dir = root / "static"
dist_dir = root / "dist"
posts_out_dir = dist_dir / "posts"


# -----------------------------
# Templates
# -----------------------------

env = Environment(
    loader=FileSystemLoader(templates_dir),
    trim_blocks=True,
    lstrip_blocks=True,
    autoescape=select_autoescape(["html", "jinja"]),
)

post_template = env.get_template("post.jinja")
index_template = env.get_template("index.jinja")
generated_at_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


# -----------------------------
# Config
# -----------------------------

asset_types = {
    ".jpg": "image",
    ".jpeg": "image",
    ".png": "image",
    ".gif": "image",
    ".webp": "image",
    ".svg": "image",
    ".avif": "image",
    ".mp4": "video",
    ".mov": "video",
    ".mkv": "video",
    ".webm": "video",
    ".ogv": "video",
    ".mp3": "audio",
    ".m4a": "audio",
    ".wav": "audio",
    ".flac": "audio",
    ".ogg": "audio",
    ".pdf": "pdf",
    ".txt": "text",
    ".md": "text",
    ".csv": "text",
    ".log": "text",
    ".srt": "text",
    ".odt": "file",
}

readme_names = {"readme.md", "readme.txt"}

month_names = {f"{i:02}": month_name[i] for i in range(1, 13)}
birthday = date(2005, 10, 18)


# -----------------------------
# Helpers
# -----------------------------


def prettify(html: str) -> str:
    """Format html for readable output."""
    return BeautifulSoup(html, "html.parser").prettify()


def asset_kind(path: Path) -> str:
    """Get the asset kind from file extension."""
    suffix = path.suffix.lower()
    if suffix and suffix not in asset_types:
        print(
            f"Warning: Unsupported file extension '{suffix}' for '{path.relative_to(root)}'. "
            "Treating it as a generic file asset."
        )

    return asset_types.get(suffix, "file")


def is_readme(path: Path) -> bool:
    """Check if a file is a readme."""
    return path.name.lower() in readme_names


def find_readme(folder: Path) -> Path | None:
    """Find the readme file in a folder."""
    for path in folder.iterdir():
        if path.is_file() and is_readme(path):
            return path

    return None


def clear_folder(folder: Path) -> None:
    """Clear a folder without removing it."""
    if not folder.exists():
        folder.mkdir()
        return

    for path in folder.iterdir():
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()


def post_date(slug: str) -> date | None:
    """Return the date for YYYY-MM-DD slugs."""
    try:
        return datetime.strptime(slug[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def post_weekday(slug: str) -> str | None:
    """Return the weekday for YYYY-MM-DD slugs."""
    dated_post = post_date(slug)
    if dated_post is None:
        return None

    return dated_post.strftime("%A")


def post_age(slug: str) -> int | None:
    """Return the age in years for YYYY-MM-DD slugs."""
    dated_post = post_date(slug)
    if dated_post is None or dated_post < birthday:
        return None

    return (
        dated_post.year
        - birthday.year
        - ((dated_post.month, dated_post.day) < (birthday.month, birthday.day))
    )


def format_file_size(size_bytes: int) -> str:
    """Return a compact human-readable size label."""
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(size_bytes)

    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)}{unit}"

            if size.is_integer():
                return f"{int(size)}{unit}"

            return f"{size:.1f}{unit}"

        size /= 1024


# -----------------------------
# Prepare output
# -----------------------------

clear_folder(dist_dir)
posts_out_dir.mkdir(exist_ok=True)

css = static_dir / "style.css"
if css.exists():
    shutil.copy(css, dist_dir / "style.css")


# -----------------------------
# Build posts
# -----------------------------

posts = []

for folder in sorted(content_dir.iterdir(), reverse=True):
    if not folder.is_dir():
        continue

    slug = folder.name
    title = slug
    readme = find_readme(folder)
    content = ""

    if readme:
        text = readme.read_text(encoding="utf-8")
        content = markdown.markdown(text, extensions=["extra"])

    assets = []

    for path in sorted(folder.rglob("*")):
        if not path.is_file():
            continue

        if is_readme(path):
            continue

        relative_path = path.relative_to(folder)
        relative_url = "/".join(quote(part) for part in relative_path.parts)
        kind = asset_kind(path)
        size = format_file_size(path.stat().st_size)

        asset = {
            "name": str(relative_path),
            "url": f"/media/{slug}/{relative_url}",
            "kind": kind,
            "size": size,
        }

        if kind == "text":
            asset["content"] = path.read_text(encoding="utf-8", errors="replace")

        assets.append(asset)

    year = slug[:4]
    month_number = slug[5:7]
    month = month_names.get(month_number, month_number)

    posts.append(
        {
            "slug": slug,
            "title": title,
            "weekday": post_weekday(slug),
            "age": post_age(slug),
            "year": year,
            "month": month,
            "content": content,
            "assets": assets,
        }
    )


# -----------------------------
# Link neighboring posts
# -----------------------------

for index, post in enumerate(posts):
    post["older_post"] = posts[index - 1] if index > 0 else None
    post["newer_post"] = posts[index + 1] if index < len(posts) - 1 else None


# -----------------------------
# Build archive
# -----------------------------

archive = defaultdict(lambda: defaultdict(list))

for post in posts:
    archive[post["year"]][post["month"]].append(post)


# -----------------------------
# Load about page
# -----------------------------

about = ""
about_path = content_dir / "README.md"

if about_path.exists():
    about_text = about_path.read_text(encoding="utf-8")
    about = markdown.markdown(about_text, extensions=["extra"])


# -----------------------------
# Write index
# -----------------------------

index_html = index_template.render(
    archive=archive,
    about=about,
    css_href="style.css",
    home_href="index.html",
    post_href_prefix="posts/",
    page_count=len(posts),
    generated_at_utc=generated_at_utc,
)

index_output = dist_dir / "index.html"
index_output.write_text(prettify(index_html), encoding="utf-8")


# -----------------------------
# Write post pages
# -----------------------------

for post in posts:
    html = post_template.render(
        title=post["title"],
        weekday=post["weekday"],
        age=post["age"],
        content=post["content"],
        assets=post["assets"],
        archive=archive,
        css_href="../style.css",
        home_href="../index.html",
        post_href_prefix="",
        current_slug=post["slug"],
        page_count=len(posts),
        newer_post=post["newer_post"],
        older_post=post["older_post"],
        generated_at_utc=generated_at_utc,
    )

    post_output = posts_out_dir / f"{post['slug']}.html"
    post_output.write_text(prettify(html), encoding="utf-8")


# -----------------------------
# Done
# -----------------------------

print(f"Wrote {index_output}")
print(f"Wrote {len(posts)} post(s)")
