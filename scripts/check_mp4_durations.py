import argparse
import subprocess
from os import fstat, fsync
from os.path import samestat
from pathlib import Path
from shutil import chown, which
from stat import S_IMODE, S_ISREG
from struct import Struct, unpack
from tempfile import TemporaryDirectory
from typing import BinaryIO


def find_atom(file: BinaryIO, name: bytes, start: int, end: int) -> tuple[int, int]:
    """Find an atom and return the bounds of its payload."""
    while start < end:
        file.seek(start)
        header = file.read(min(8, end - start))
        if len(header) != 8:
            raise ValueError(f"truncated atom header at byte {start}")

        size, atom_type = unpack(">I4s", header)
        if size == 1:
            extended_size = file.read(min(8, end - start - 8))
            if len(extended_size) != 8:
                raise ValueError(f"truncated extended atom size at byte {start}")
            (size,) = unpack(">Q", extended_size)
        elif size == 0:
            size = end - start

        payload = file.tell()
        atom_end = start + size
        if not payload <= atom_end <= end:
            raise ValueError(f"invalid atom size at byte {start}")
        if atom_type == name:
            return payload, atom_end
        start = atom_end

    raise ValueError(f"{name.decode()} atom not found")


def read_movie_duration(path: Path, *, require_faststart: bool = False) -> float | None:
    """Read the duration declared by moov/mvhd, in seconds."""
    with path.open("rb") as file:
        file_size = fstat(file.fileno()).st_size
        moov_start, moov_end = find_atom(file, b"moov", 0, file_size)
        if require_faststart:
            mdat_start, mdat_end = find_atom(file, b"mdat", 0, file_size)
            if moov_end > mdat_start or mdat_start == mdat_end:
                raise ValueError("expected moov before nonempty media data")
        start, end = find_atom(file, b"mvhd", moov_start, moov_end)
        file.seek(start)
        payload = file.read(min(32, end - start))

    if not payload:
        raise ValueError("empty mvhd atom")

    version = payload[0]
    if version == 0:
        fields = Struct(">12xII")
        unknown_duration = (1 << 32) - 1
    elif version == 1:
        fields = Struct(">20xIQ")
        unknown_duration = (1 << 64) - 1
    else:
        raise ValueError(f"unsupported mvhd version {version}")

    if len(payload) < fields.size:
        raise ValueError("truncated mvhd duration fields")
    timescale, duration = fields.unpack_from(payload)
    if timescale == 0:
        raise ValueError("mvhd timescale is zero")
    if duration == unknown_duration:
        return None
    return duration / timescale


def remux_faststart(path: Path, ffmpeg: str) -> float:
    """Replace a zero-duration recording with a validated stream copy."""
    path = path.absolute()
    original = path.lstat()
    if not S_ISREG(original.st_mode):
        raise ValueError("replacement requires a regular file")
    if read_movie_duration(path) != 0:
        raise ValueError("source duration changed during the scan")

    with TemporaryDirectory(prefix=".faststart-", dir=path.parent) as folder:
        output = Path(folder) / "video.tmp"
        result = subprocess.run(
            [
                ffmpeg,
                "-nostdin",
                "-loglevel",
                "error",
                "-xerror",
                "-n",
                "-i",
                str(path),
                "-map",
                "0",
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                "-f",
                "mp4",
                str(output),
            ],
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
        )
        if result.returncode:
            raise ValueError(
                result.stderr.strip() or f"FFmpeg exited with {result.returncode}"
            )

        duration = read_movie_duration(output, require_faststart=True)
        if duration is None or duration <= 0:
            raise ValueError("remuxed file has no positive movie header duration")

        output_stat = output.stat()
        if (output_stat.st_uid, output_stat.st_gid) != (
            original.st_uid,
            original.st_gid,
        ):
            chown(output, user=original.st_uid, group=original.st_gid)
        with output.open("rb") as file:
            output.chmod(S_IMODE(original.st_mode))
            fsync(file.fileno())

        current = path.lstat()
        if (
            not samestat(original, current)
            or current.st_size != original.st_size
            or current.st_mtime_ns != original.st_mtime_ns
            or current.st_ctime_ns != original.st_ctime_ns
        ):
            raise ValueError("source changed during the remux")

        output.replace(path)
    return duration


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Print the movie header duration for each MP4 file in a directory tree."
    )
    parser.add_argument(
        "directory",
        nargs="?",
        type=Path,
        default=Path.cwd(),
        help="Directory to scan recursively (default: current directory).",
    )
    parser.add_argument(
        "--faststart",
        action="store_true",
        help="Use FFmpeg to remux zero-duration MP4s and replace them after validation.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Also print files with positive or unknown durations.",
    )
    args = parser.parse_args()
    if not args.directory.is_dir():
        parser.error(f"not a directory: {args.directory}")

    ffmpeg = which("ffmpeg") if args.faststart else None
    if args.faststart and ffmpeg is None:
        parser.error("--faststart requires ffmpeg on PATH")

    mp4_files = sorted(
        path
        for path in args.directory.rglob("*")
        if path.name.lower().endswith(".mp4") and path.is_file()
    )
    if not mp4_files:
        print("No MP4 files found.")

    failed = False
    for path in mp4_files:
        try:
            seconds = read_movie_duration(path)
            if seconds == 0 and ffmpeg is not None:
                print(f"REMUXING\t{path}", flush=True)
                seconds = remux_faststart(path, ffmpeg)
                if args.verbose:
                    print(f"FIXED\t{seconds:.12g} s\t{path}")
                continue
        except (OSError, ValueError) as error:
            print(f"ERROR\t{path}\t{error}")
            failed = True
        else:
            if seconds == 0:
                print(f"ZERO\t{path}")
            elif args.verbose:
                result = "UNKNOWN" if seconds is None else f"{seconds:.12g} s"
                print(f"{result}\t{path}")

    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
