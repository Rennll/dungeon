#!/usr/bin/env python3
"""Split large TXT sources into connector-friendly forensic samples.

The splitter preserves source text content and whitespace semantics. It does
not infer paragraphs or normalize indentation. Input line endings are
canonicalized to LF only so blank-line detection is stable across CRLF/CR/LF
sources; output is UTF-8.

Modes:
  chunks   Split the source into small UTF-8 files, preferring blank boundaries.
  forensic Write targeted samples around indentation transitions and blank runs.
  both     Produce both kinds of output (default).
"""
from __future__ import annotations

import argparse
import codecs
from collections import Counter
from pathlib import Path

U3000 = "\u3000"
WS = " \t\u3000"


def read_source(path: Path) -> tuple[str, str, bool]:
    raw = path.read_bytes()
    bom = False
    if raw.startswith(codecs.BOM_UTF8):
        encoding = "utf-8-sig"
        bom = True
    elif raw.startswith(codecs.BOM_UTF16_LE):
        encoding = "utf-16-le"
        bom = True
    elif raw.startswith(codecs.BOM_UTF16_BE):
        encoding = "utf-16-be"
        bom = True
    else:
        encoding = "utf-8"
        for candidate in ("utf-8", "gb18030", "big5", "cp950"):
            try:
                raw.decode(candidate)
                encoding = candidate
                break
            except UnicodeDecodeError:
                continue

    try:
        text = raw.decode(encoding)
    except UnicodeDecodeError:
        text = raw.decode(encoding, errors="replace")
        encoding += " (errors=replace)"

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text, encoding, bom


def leading(line: str) -> str:
    i = 0
    while i < len(line) and line[i] in WS:
        i += 1
    return line[:i]


def category(line: str) -> str:
    if line.strip(WS) == "":
        return "BLANK"
    prefix = leading(line)
    if not prefix:
        return "NO_INDENT"
    if set(prefix) == {U3000}:
        return f"U+3000x{len(prefix)}"
    if set(prefix) == {" "}:
        return f"ASCII_SPACE_x{len(prefix)}"
    if set(prefix) == {"\t"}:
        return f"TABx{len(prefix)}"
    return "MIXED"


def blank_runs(lines: list[str]) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    i = 0
    while i < len(lines):
        if category(lines[i]) != "BLANK":
            i += 1
            continue
        start = i
        while i < len(lines) and category(lines[i]) == "BLANK":
            i += 1
        runs.append((start, i))
    return runs


def transitions(lines: list[str]) -> list[tuple[int, str, str]]:
    """Return (zero-based current-line index, previous category, current)."""
    result: list[tuple[int, str, str]] = []
    previous: str | None = None
    for i, line in enumerate(lines):
        current = category(line)
        if current == "BLANK":
            previous = None
            continue
        if previous is not None and previous != current:
            result.append((i, previous, current))
        previous = current
    return result


def write_context(
    out: list[str],
    lines: list[str],
    center_start: int,
    center_end: int,
    before: int,
    after: int,
    highlight: set[int],
) -> None:
    start = max(0, center_start - before)
    end = min(len(lines), center_end + after)
    for i in range(start, end):
        marker = ">>" if i in highlight else "  "
        out.append(f"{marker} {i + 1:7d} {category(lines[i]):18s} {lines[i]!r}")


def event_key(kind: str, value: tuple) -> str:
    if kind == "transition":
        return f"{value[0]} -> {value[1]}"
    return f"blank run x{value[0]}"


def build_forensic(lines: list[str], limit: int) -> dict[str, list[tuple]]:
    events: dict[str, list[tuple]] = {}
    for line_no, previous, current in transitions(lines):
        key = event_key("transition", (previous, current))
        events.setdefault(key, [])
        if len(events[key]) < limit:
            events[key].append((line_no, previous, current))

    for start, end in blank_runs(lines):
        key = event_key("blank", (end - start,))
        events.setdefault(key, [])
        if len(events[key]) < limit:
            events[key].append((start, end))
    return events


def write_forensic(
    path: Path,
    source: Path,
    lines: list[str],
    limit: int,
    before: int,
    after: int,
) -> None:
    events = build_forensic(lines, limit)
    text = [
        "=" * 80,
        f"FORENSIC TXT SAMPLE: {source}",
        "=" * 80,
        "Whitespace is shown with repr(); source line numbers are 1-based.",
        "No paragraph inference is performed.",
    ]

    for key in sorted(events):
        text.extend(["", f"[{key}] cases: {len(events[key])}", "-" * 80])
        for number, event in enumerate(events[key], 1):
            if key.startswith("blank run x"):
                start, end = event
                text.append(f"\nCASE B{number:02d}: blank lines {start + 1}-{end}")
                write_context(text, lines, start, end, before, after, set(range(start, end)))
            else:
                line_no, previous, current = event
                text.append(f"\nCASE T{number:02d}: transition at lines {line_no}->{line_no + 1}")
                write_context(text, lines, line_no - 1, line_no + 1, before, after, {line_no - 1, line_no})

    path.write_text("\n".join(text) + "\n", encoding="utf-8")


def split_chunks(lines: list[str], max_bytes: int) -> list[tuple[int, int, int, bool]]:
    """Return (start, end, UTF-8 bytes, oversize-single-line)."""
    chunks: list[tuple[int, int, int, bool]] = []
    start = 0
    n = len(lines)

    while start < n:
        size = 0
        i = start
        last_good_boundary: int | None = None
        size_at_boundary = 0
        boundary_floor = int(max_bytes * 0.75)

        while i < n:
            piece_size = len((lines[i] + "\n").encode("utf-8"))
            if i > start and size + piece_size > max_bytes:
                break
            size += piece_size
            i += 1
            if category(lines[i - 1]) == "BLANK" and size >= boundary_floor:
                last_good_boundary = i
                size_at_boundary = size

        if i == start:
            # A single pathological line may exceed the target size. Keep it
            # intact rather than splitting inside a line.
            i = start + 1
            size = len((lines[start] + "\n").encode("utf-8"))
            chunks.append((start, i, size, True))
            start = i
            continue

        if i < n and last_good_boundary is not None:
            i = last_good_boundary
            size = size_at_boundary

        chunks.append((start, i, size, size > max_bytes))
        start = i

    return chunks


def write_chunks(
    output_dir: Path,
    prefix: str,
    source: Path,
    lines: list[str],
    max_bytes: int,
) -> list[tuple[Path, int, int, int, bool]]:
    ranges = split_chunks(lines, max_bytes)
    result = []
    for number, (start, end, byte_count, oversize) in enumerate(ranges, 1):
        path = output_dir / f"{prefix}_{source.stem}_chunk_{number:03d}.txt"
        path.write_text("\n".join(lines[start:end]) + "\n", encoding="utf-8")
        result.append((path, start + 1, end, byte_count, oversize))
    return result


def write_index(
    output_dir: Path,
    prefix: str,
    source: Path,
    lines: list[str],
    encoding: str,
    bom: bool,
    chunks: list[tuple[Path, int, int, int, bool]],
    max_bytes: int,
) -> None:
    cats = Counter(category(line) for line in lines)
    runs = Counter(end - start for start, end in blank_runs(lines))
    transitions_count = len(transitions(lines))
    content = [
        "=" * 80,
        f"SPLIT INDEX: {source}",
        "=" * 80,
        f"detected_encoding: {encoding}",
        f"BOM: {'yes' if bom else 'no'}",
        "output_encoding: utf-8",
        "output_line_endings: LF",
        f"lines: {len(lines)}",
        f"chunk_target_bytes: {max_bytes}",
        f"chunks: {len(chunks)}",
        f"nonblank indentation transitions (blank lines reset): {transitions_count}",
        "",
        "--- line categories ---",
    ]
    content.extend(f"{key}: {value}" for key, value in cats.most_common())
    content.append("")
    content.append("--- blank-line runs ---")
    content.extend(f"x{key}: {value}" for key, value in sorted(runs.items()))
    content.append("")
    content.append("--- chunk files ---")
    for path, start, end, byte_count, oversize in chunks:
        suffix = "  [OVERSIZE SINGLE LINE]" if oversize else ""
        content.append(f"{path.name}: lines {start}-{end}, utf8_bytes={byte_count}{suffix}")
    (output_dir / f"{prefix}_{source.stem}_index.txt").write_text(
        "\n".join(content) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="large TXT source")
    parser.add_argument("--output-dir", type=Path, default=Path("analysis/samples"))
    parser.add_argument("--prefix", default="sample")
    parser.add_argument("--mode", choices=("chunks", "forensic", "both"), default="both")
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=65536,
        help="target UTF-8 size per chunk; lines are never split",
    )
    parser.add_argument("--limit", type=int, default=20, help="examples per forensic event")
    parser.add_argument("--context-before", type=int, default=8)
    parser.add_argument("--context-after", type=int, default=8)
    args = parser.parse_args()

    if args.max_bytes < 1024 or args.limit < 1 or args.context_before < 0 or args.context_after < 0:
        parser.error("max-bytes must be >= 1024; limit must be positive; context values must be non-negative")
    if not args.source.is_file():
        parser.error(f"source file not found: {args.source}")

    text, encoding, bom = read_source(args.source)
    lines = text.split("\n")
    # Avoid inventing an extra source line when the file ends with LF.
    if lines and lines[-1] == "":
        lines.pop()

    args.output_dir.mkdir(parents=True, exist_ok=True)

    chunks = []
    if args.mode in {"chunks", "both"}:
        chunks = write_chunks(args.output_dir, args.prefix, args.source, lines, args.max_bytes)
        write_index(args.output_dir, args.prefix, args.source, lines, encoding, bom, chunks, args.max_bytes)

    if args.mode in {"forensic", "both"}:
        write_forensic(
            args.output_dir / f"{args.prefix}_{args.source.stem}_forensic.txt",
            args.source,
            lines,
            args.limit,
            args.context_before,
            args.context_after,
        )

    print(f"source: {args.source}")
    print(f"detected encoding: {encoding}")
    print(f"lines: {len(lines)}")
    if chunks:
        print(f"chunks: {len(chunks)}")
        print(f"index: {args.prefix}_{args.source.stem}_index.txt")
    if args.mode in {"forensic", "both"}:
        print(f"forensic: {args.prefix}_{args.source.stem}_forensic.txt")


if __name__ == "__main__":
    main()
