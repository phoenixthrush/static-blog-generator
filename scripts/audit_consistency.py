import argparse
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from stat import S_ISDIR, S_ISLNK, S_ISREG
from unicodedata import normalize
from urllib.parse import unquote

SMB_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
SMB_DEVICES = re.compile(r"(?:con|prn|aux|nul|(?:com|lpt)[1-9¹²³])", re.IGNORECASE)
ODD_SPACE = re.compile(r"[^\S ]| {2,}|[\u200b\u2060\ufeff]")
YEAR_FIRST_DATE = re.compile(r"([0-9]{4})[-_. ]([0-9]{1,2})[-_. ]([0-9]{1,2})")
ORIGINALS_NAME = re.compile(r"originals?(?:[\s_-]+archives?)?")
ARCHIVE_EXTENSIONS = (
    ".tar.gz",
    ".tar.bz2",
    ".tar.xz",
    ".zip",
    ".7z",
    ".rar",
    ".tar",
    ".tgz",
)
PARTIAL_EXTENSIONS = (".part", ".partial", ".crdownload", ".download", ".aria2")
OS_LEFTOVERS = {".ds_store", "thumbs.db", "desktop.ini", "__macosx"}
JPEG_EXTENSIONS = {".jpg", ".jpeg", ".jpe", ".jfif"}
README_NAMES = {"readme", "readme.md", "readme.txt"}
TEXT_EXTENSIONS = {
    ".csv",
    ".html",
    ".ini",
    ".json",
    ".log",
    ".markdown",
    ".md",
    ".nfo",
    ".rst",
    ".srt",
    ".toml",
    ".tsv",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
FOLDERS_HEADING = re.compile(r"\s*(?:#+\s*)?folders\s*:\s*", re.IGNORECASE)
FOLDER_BULLET = re.compile(r"\s*[-*+]\s+\S.*")


def folded(name: str) -> str:
    """Compare names without case or Unicode normalization differences."""
    return normalize("NFC", normalize("NFC", name).casefold())


def collision_key(name: str) -> str:
    return folded(name.rstrip(" ."))


def is_originals_archive(name: str, is_dir: bool) -> bool:
    name = name.casefold().strip(" ._-")
    if not is_dir:
        extension = next((ext for ext in ARCHIVE_EXTENSIONS if name.endswith(ext)), "")
        if not extension:
            return False
        name = name.removesuffix(extension)
    return ORIGINALS_NAME.fullmatch(name) is not None


def is_garbled(name: str) -> bool:
    if "\ufffd" in name or any("\ud800" <= char <= "\udfff" for char in name):
        return True
    # Common UTF-8 lead bytes misread as Windows-1252 or Latin-1.
    lead_lengths = {"Â": 2, "Ã": 2, "Ð": 2, "Ñ": 2, "â": 3, "ï": 3, "ð": 4}
    for index, char in enumerate(name):
        if char not in lead_lengths:
            continue
        fragment = name[index : index + lead_lengths[char]]
        for encoding in ("cp1252", "latin-1"):
            try:
                fragment.encode(encoding).decode("utf-8")
            except UnicodeError:
                continue
            return True
    return False


def iso_folder_name(name: str) -> str | None:
    match = YEAR_FIRST_DATE.fullmatch(name)
    if match:
        try:
            return date(*map(int, match.groups())).isoformat()
        except ValueError:
            pass
    return None


def is_reserved(name: str) -> bool:
    return SMB_DEVICES.fullmatch(name.partition(".")[0].rstrip(" ")) is not None


def folders_list_is_formatted(lines: list[str], heading: int) -> bool:
    if heading != 0 or lines[:2] != ["folders:", ""] or len(lines) < 3:
        return False
    index = 2
    while index < len(lines) and FOLDER_BULLET.fullmatch(lines[index]):
        line = lines[index]
        if not re.fullmatch(r"- \S.*", line) or line != line.rstrip():
            return False
        index += 1
    return index > 2 and (index == len(lines) or lines[index] == "")


@dataclass
class Audit:
    root: Path
    verbose: bool = False
    problems: list[str] = field(default_factory=list)
    style: list[str] = field(default_factory=list)
    renames: dict[Path, str] = field(default_factory=dict)
    children: dict[Path, list[Path]] = field(default_factory=dict)
    folders: set[Path] = field(default_factory=set)
    files: dict[Path, int] = field(default_factory=dict)
    excluded_archives: set[Path] = field(default_factory=set)
    references: list[str] = field(default_factory=list)
    symlinks: int = 0

    def label(self, path: Path) -> str:
        return repr(path.relative_to(self.root).as_posix())

    def progress(self, message: str) -> None:
        if self.verbose:
            print(message, flush=True)

    def scan(self) -> None:
        pending = [self.root]
        while pending:
            folder = pending.pop()
            self.folders.add(folder)
            self.progress(f"Scanning folder {self.label(folder)}")
            try:
                entries = sorted(folder.iterdir())
            except OSError as error:
                self.problems.append(
                    f"{self.label(folder)}: cannot scan folder ({error.strerror})"
                )
                continue
            self.children[folder] = entries
            if not entries:
                self.problems.append(f"{self.label(folder)}: empty folder")

            for path in entries:
                try:
                    info = path.lstat()
                except OSError as error:
                    self.problems.append(
                        f"{self.label(path)}: cannot inspect entry ({error.strerror})"
                    )
                    continue
                if S_ISLNK(info.st_mode):
                    self.symlinks += 1
                    self.progress(f"Skipping symlink {self.label(path)}")
                    self.problems.append(f"{self.label(path)}: symlink skipped")
                    continue
                is_dir = S_ISDIR(info.st_mode)
                if is_originals_archive(path.name, is_dir):
                    self.excluded_archives.add(path)
                    self.progress(f"Skipping originals archive {self.label(path)}")
                    continue
                if is_dir:
                    pending.append(path)
                elif S_ISREG(info.st_mode):
                    self.files[path] = info.st_size
                    self.progress(
                        f"Found file {self.label(path)} ({info.st_size} bytes)"
                    )
                else:
                    self.progress(
                        f"Skipping special filesystem entry {self.label(path)}"
                    )
                    self.problems.append(
                        f"{self.label(path)}: special filesystem entry skipped"
                    )

    def check_name(self, path: Path, *, is_file: bool) -> None:
        name = path.name
        label = self.label(path)
        lower = name.casefold()
        if lower in OS_LEFTOVERS or name.startswith("._"):
            self.problems.append(f"{label}: OS leftover, review for removal")
            return
        if lower.rstrip(" .").endswith(PARTIAL_EXTENSIONS):
            self.problems.append(
                f"{label}: possible partial download, check before keeping"
            )
        if is_garbled(name):
            self.problems.append(
                f"{label}: possible garbled Unicode, verify the original spelling"
            )
        if SMB_CHARACTERS.search(name) or is_reserved(name):
            self.problems.append(
                f"{label}: Windows/SMB reserved character or device name"
            )
        if name.endswith((".", " ")):
            self.problems.append(
                f"{label}: trailing dot or space can cause SMB access problems"
            )
        if name != name.strip() or ODD_SPACE.search(name):
            self.problems.append(f"{label}: unusual whitespace")

        candidate = re.sub(r"[\u200b\u2060\ufeff]", "", name)
        candidate = re.sub(r"\s+", " ", candidate).strip().rstrip(" .")
        candidate = SMB_CHARACTERS.sub("-", candidate)
        if is_reserved(candidate):
            candidate = "_" + candidate

        if is_file:
            suffix = Path(candidate).suffix
            preferred = ".jpeg" if suffix.lower() in JPEG_EXTENSIONS else suffix.lower()
            if suffix != preferred:
                self.style.append(f"{label}: use {preferred} for the extension")
                candidate = candidate.removesuffix(suffix) + preferred
        elif path.parent == self.root:
            iso_name = iso_folder_name(candidate)
            if name != iso_name:
                hint = ", choose the date manually" if iso_name is None else ""
                self.problems.append(
                    f"{label}: top-level folder needs a valid YYYY-MM-DD date{hint}"
                )
                # Keep ambiguous or invalid dates for manual review.
                candidate = iso_name or name

        if candidate and candidate != name:
            self.renames[path] = candidate

    def read_text(self, path: Path) -> str:
        self.progress(f"Reading text file {self.label(path)}")
        try:
            data = path.read_bytes()
        except OSError as error:
            self.problems.append(
                f"{self.label(path)}: cannot read text ({error.strerror})"
            )
            return ""
        if data.startswith((b"\xff\xfe", b"\xfe\xff")):
            return data.decode("utf-16", errors="replace")
        try:
            return data.decode("utf-8-sig")
        except UnicodeDecodeError:
            return data.decode("cp1252", errors="replace")

    def check_readmes(self) -> None:
        for path in self.files:
            if path.name.casefold() not in README_NAMES:
                continue
            lines = self.read_text(path).splitlines()
            heading = next(
                (i for i, line in enumerate(lines) if FOLDERS_HEADING.fullmatch(line)),
                None,
            )
            if heading is None:
                continue
            label = self.label(path)
            if path.name != "README.txt":
                self.style.append(
                    f"{label}: use README.txt for the removed folders list"
                )
                self.renames[path] = "README.txt"
            if not folders_list_is_formatted(lines, heading):
                self.style.append(
                    f"{label}: put 'folders:' at the top, then a blank line and '- ' bullets. "
                    "Keep existing notes below the list, separated by a blank line."
                )

        empty_by_parent = defaultdict(list)
        for folder, entries in self.children.items():
            if folder != self.root and not entries:
                empty_by_parent[folder.parent].append(folder.name)
        for parent, names in empty_by_parent.items():
            if not any(
                path in self.files and self.renames.get(path, path.name) == "README.txt"
                for path in self.children[parent]
            ):
                self.style.append(
                    f"{self.label(parent)}: if removing {', '.join(map(repr, sorted(names)))}, "
                    "record the names in a README.txt folders list"
                )

    def check_collisions(self) -> None:
        for folder, entries in self.children.items():
            current = defaultdict(set)
            proposed = defaultdict(set)
            excluded = set()
            for path in entries:
                current[collision_key(path.name)].add(path.name)
                if path in self.excluded_archives:
                    excluded.add(path.name)
                if path in self.renames:
                    proposed[collision_key(self.renames[path])].add(path.name)
            for names in current.values():
                if len(names) > 1 and names - excluded:
                    self.problems.append(
                        f"{self.label(folder)}: case, normalization, or SMB name collision "
                        f"between {', '.join(map(repr, sorted(names)))}"
                    )
            for key, sources in proposed.items():
                names = sources | current.get(key, set())
                if len(names) > 1:
                    self.problems.append(
                        f"{self.label(folder)}: proposed renames conflict between "
                        f"{', '.join(map(repr, sorted(names)))}"
                    )

    def check_references(self) -> None:
        nearby_renames = defaultdict(set)
        for path in self.renames:
            post = self.root / path.relative_to(self.root).parts[0]
            for folder in {path.parent, path.parent.parent, post, path}:
                nearby_renames[folder].add(path)

        for note in self.files:
            targets = nearby_renames.get(note.parent)
            if not targets or (
                note.suffix.lower() not in TEXT_EXTENSIONS
                and note.name.casefold() not in README_NAMES
            ):
                continue
            patterns = {
                path: re.compile(
                    r"(?<![\w.-])" + re.escape(folded(path.name)) + r"(?![\w-]|\.\w)"
                )
                for path in sorted(targets)
                if path != note
            }
            for number, line in enumerate(self.read_text(note).splitlines(), start=1):
                plain, decoded = folded(line), folded(unquote(line))
                matched = [
                    path
                    for path, pattern in patterns.items()
                    if pattern.search(plain) or pattern.search(decoded)
                ]
                for path in matched:
                    self.references.append(
                        f"{self.label(note)} line {number}: review reference to {self.label(path)}"
                    )
                    del patterns[path]
                if not patterns:
                    break

    def run(self) -> None:
        self.progress(f"Auditing {str(self.root)!r}")
        self.scan()
        self.progress("Checking dates, names, extensions, and file sizes")
        for folder in sorted(self.folders - {self.root}):
            self.check_name(folder, is_file=False)
        for path, size in sorted(self.files.items()):
            self.check_name(path, is_file=True)
            if size == 0:
                self.problems.append(f"{self.label(path)}: zero-byte file")
        self.progress("Checking README folder lists")
        self.check_readmes()
        self.progress("Checking name collisions")
        self.check_collisions()
        self.progress("Checking nearby text references")
        self.check_references()

    def print_report(self) -> None:
        renames = [
            f"{self.label(path)} -> {target!r}"
            for path, target in sorted(self.renames.items())
        ]
        sections = (
            ("Problems to review", self.problems),
            ("Optional style changes", self.style),
            ("Proposed names to review", renames),
            ("Text references to review before renaming", self.references),
        )
        if not self.verbose and not any(findings for _, findings in sections):
            return

        print(f"Audit of {str(self.root)!r}")
        print(
            f"Scanned {len(self.files)} file(s) and {len(self.folders)} folder(s) including the root. "
            f"Skipped {self.symlinks} symlink(s) and {len(self.excluded_archives)} originals archive(s)."
        )
        for title, findings in sections:
            if not findings:
                continue
            print(f"\n{title} ({len(findings)})")
            for finding in sorted(findings):
                print(f"- {finding}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only audit of journal files and folders, skipping originals archives.",
        epilog="Exit status 1 means the audit found problems. Style suggestions alone return 0.",
    )
    parser.add_argument(
        "directory",
        nargs="?",
        type=Path,
        default=Path.cwd(),
        help="Directory to audit (default: current directory).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show every scanned file and folder, skipped entries, and audit progress.",
    )
    args = parser.parse_args()
    root = args.directory.expanduser().absolute()
    if root.is_symlink() or not root.is_dir():
        parser.error(f"expected a directory that is not a symlink: {root}")

    audit = Audit(root, verbose=args.verbose)
    audit.run()
    audit.print_report()
    return int(bool(audit.problems))


if __name__ == "__main__":
    raise SystemExit(main())
