import argparse
import shutil
import subprocess
import sys
from calendar import month_name
from collections import defaultdict
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path
from urllib.parse import quote

import markdown
from bs4 import BeautifulSoup
from jinja2 import Environment, FileSystemLoader, select_autoescape

# -----------------------------
# Paths
# -----------------------------

root = Path(__file__).parent
parser = argparse.ArgumentParser(description="Build the static journal.")
parser.add_argument(
    "--demo",
    action="store_true",
    help="Build the bundled sample journal with its assets.",
)
parser.add_argument(
    "--bundle-media",
    action="store_true",
    help="Copy post assets into dist so the site can be opened without a server.",
)
args = parser.parse_args()

content_dir = root / "examples" / "content" if args.demo else root / "content"
templates_dir = root / "templates"
static_dir = root / "static"
dist_dir = root / "dist"
posts_out_dir = dist_dir / "posts"
thumbnails_dir = dist_dir / "thumbnails"
bundle_media = args.demo or args.bundle_media

if not content_dir.is_dir():
    parser.error(
        f"Content directory not found: {content_dir}. Try --demo for sample posts."
    )


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
generated_at_utc = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


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
    return BeautifulSoup(
        html, "html.parser", preserve_whitespace_tags={"pre", "textarea", "p"}
    ).prettify()


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


def post_days_since(slug: str) -> int | None:
    """Return the number of days since the post date."""
    dated_post = post_date(slug)
    if dated_post is None:
        return None

    return (date.today() - dated_post).days


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


def build_video_poster(path: Path) -> str | None:
    """Extract the first video frame as a small JPEG in the build output."""
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-i",
                str(path),
                "-map",
                "0:V:0",
                "-frames:v",
                "1",
                # Fit within 640px without upscaling, using the display aspect ratio.
                "-vf",
                (
                    "scale='max(1,min(640,min(640,ih)*dar))':"
                    "'max(1,min(640,min(ih,640/dar)))',setsar=1"
                ),
                "-c:v",
                "mjpeg",
                "-q:v",
                "5",
                "-f",
                "image2pipe",
                "pipe:1",
            ],
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        detail = str(error)
    else:
        if result.returncode == 0 and result.stdout:
            filename = f"{sha256(result.stdout).hexdigest()}.jpg"
            thumbnails_dir.mkdir(exist_ok=True)
            (thumbnails_dir / filename).write_bytes(result.stdout)
            return f"../thumbnails/{filename}"

        detail = result.stderr.decode(errors="replace").strip() or "no frame decoded"

    print(
        f"Warning: Could not generate poster for '{path.relative_to(content_dir)}': {detail}",
        file=sys.stderr,
    )
    return None


# -----------------------------
# Prepare output
# -----------------------------

clear_folder(dist_dir)
posts_out_dir.mkdir(exist_ok=True)

shutil.copytree(static_dir, dist_dir, dirs_exist_ok=True)

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
        media_path = path.relative_to(content_dir)
        kind = asset_kind(path)
        size = format_file_size(path.stat().st_size)

        asset = {
            "name": str(relative_path),
            "url": f"../media/{quote(media_path.as_posix())}",
            "kind": kind,
            "size": size,
        }

        if kind == "text":
            asset["content"] = path.read_text(encoding="utf-8", errors="replace")
        elif kind == "video":
            asset["poster"] = build_video_poster(path)

        if bundle_media:
            media_output = dist_dir / "media" / media_path
            media_output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, media_output)

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
            "days_since_post": post_days_since(slug),
            "year": year,
            "month": month,
            "content": content,
            "assets": assets,
        }
    )


# -----------------------------
# Link neighboring posts
# -----------------------------

# Posts are newest first. The template intentionally places older on the left
# and newer on the right; preserve that direction when changing navigation.
for index, post in enumerate(posts):
    post["newer_post"] = posts[index - 1] if index > 0 else None
    post["older_post"] = posts[index + 1] if index < len(posts) - 1 else None


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
        days_since_post=post["days_since_post"],
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
