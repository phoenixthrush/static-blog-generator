import argparse
import re
from os import fstat
from pathlib import Path
from struct import Struct, unpack
from typing import BinaryIO

RECORDING_NAME = re.compile(
    r"\d{4}-\d{2}-\d{2} \d{2}-\d{2}-\d{2}\.mp4", re.ASCII | re.IGNORECASE
)


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


def read_movie_duration(path: Path) -> float | None:
    """Read the duration declared by moov/mvhd, in seconds."""
    with path.open("rb") as file:
        moov_start, moov_end = find_atom(file, b"moov", 0, fstat(file.fileno()).st_size)
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Print the MP4 movie header duration for timestamp-named recordings."
    )
    parser.add_argument(
        "directory",
        nargs="?",
        type=Path,
        default=Path.cwd(),
        help="Directory to scan recursively (default: current directory).",
    )
    args = parser.parse_args()
    if not args.directory.is_dir():
        parser.error(f"not a directory: {args.directory}")

    recordings = sorted(
        path
        for path in args.directory.rglob("*")
        if RECORDING_NAME.fullmatch(path.name) and path.is_file()
    )
    if not recordings:
        print("No YYYY-MM-DD HH-MM-SS.mp4 recordings found.")

    failed = False
    for path in recordings:
        try:
            seconds = read_movie_duration(path)
        except (OSError, ValueError) as error:
            print(f"ERROR\t{path}\t{error}")
            failed = True
        else:
            if seconds is None:
                result = "UNKNOWN"
            elif seconds == 0:
                result = "ZERO"
            else:
                result = f"{seconds:.12g} s"
            print(f"{result}\t{path}")

    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
