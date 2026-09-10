#!/usr/bin/env python3
"""Split large TXT sources into connector-friendly forensic samples.

The splitter is intentionally lossless: it never normalizes whitespace, changes
line endings, or attempts to infer paragraph semantics. It writes UTF-8 text
chunks with stable source line numbers so a large source can be inspected in
small GitHub-readable files.

Two modes are provided:

* ``chunks``: sequential chunks, preferably split at a blank-line boundary.
* ``forensic``: targeted samples around whitespace transitions and blank-line
  runs, with context before/after each event.

The forensic mode is designed for comparing novel-specific formatting regimes,
not for producing parser input.
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
    """Return (zero-based line index, previous category, current category)."""
    result = []
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
    transitions_by_key: dict[str, list[tuple]] = {}
    for line_no, previous, current in transitions(lines):
        key = event_key("transition", (previous, current))
        transitions_by_key.setdefault(key, [])
        if len(transitions_by_key[key]) < limit:
            transitions_by_key[key].append((line_no, previous, current))

    blanks_by_key: dict[str, list[tuple]] = {}
    for start, end in blank_runs(lines):
        key = event_key("blank", (end - start,))
        blanks_by_key.setdefault(key, [])
        if len(blanks_by_key[key]) < limit:
            blanks_by_key[key].append((start, end))

    return {**transitions_by_key, **blanks_by_key}


def write_forensic(path: Path, source: Path, lines: list[str], limit: int, before: int, after: int) -> None:
    events = build_forensic(lines, limit)
    text: list[str] = [
        "=" * 80,
        f"FORENSIC TXT SAMPLE: {source}",
        "=" * 80,
        "Whitespace is shown with repr(); source line numbers are 1-based.",
        "No whitespace normalization or paragraph inference is performed.",
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


def split_chunks(lines: list[str], max_lines: int) -> list[tuple[int, int]]:
    chunks: list[tuple[int, int]] = []
    start = 0
    while start < len(lines):
        target = min(start + max_lines, len(lines))
        if target < len(lines):
            # Prefer a nearby blank-line boundary without allowing one huge block
            # to defeat the requested size.
            boundary = target
            for i in range(target, start, -1):
                if category(lines[i - 1]) == "BLANK":
                    boundary = i
                    break
            if boundary == start:
                boundary = target
            target = boundary
        chunks.append((start, target))
        start = target
    return chunks


def write_chunks(output_dir: Path, prefix: str, source: Path, lines: list[str], max_lines: int) -> int:
    ranges = split_chunks(lines, max_lines)
    for number, (start, end) in enumerate(ranges, 1):
        path = output_dir / f"{prefix}_{source.stem}_chunk_{number:03d}.txt"
        content = [
            f"# SOURCE: {source}",
            f"# LINES: {start + 1}-{end}",
            "# NOTE: source lines below are preserved verbatim; line numbers are metadata only.",
            "",
        ]
        content.extend(lines[start:end])
        path.write_text("\n".join(content), encoding="utf-8")
    return len(ranges)


def write_index(output_dir: Path, prefix: str, source: Path, lines: list[str], encoding: str, bom: bool, chunk_count: int) -> None:
    cats = Counter(category(line) for line in lines)
    runs = Counter(end - start for start, end in blank_runs(lines))
    transitions_count = len(transitions(lines))
    content = [
        "=" * 80,
        f"SPLIT INDEX: {source}",
        "=" * 80,
        f"encoding: {encoding}",
        f"BOM: {'yes' if bom else 'no'}",
        f"lines: {len(lines)}",
        f"chunks: {chunk_count}",
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
    content.extend(f"{prefix}_{source.stem}_chunk_{i:03d}.txt" for i in range(1, chunk_count + 1))
    (output_dir / f"{prefix}_{source.stem}_index.txt").write_text("\n".join(content) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("analysis/samples"))
    parser.add_argument("--prefix", default="sample")
    parser.add_argument("--mode", choices=("chunks", "forensic", "both"), default="both")
    parser.add_argument("--max-lines", type=int, default=500)
    parser.add_argument("--limit", type=int, default=20, help="Maximum examples per forensic event")
    parser.add_argument("--context-before", type=int, default=8)
    parser.add_argument("--context-after", type=int, default=8)
    args = parser.parse_args()

    if args.max_lines < 1 or args.limit < 1 or args.context_before < 0 or args.context_after < 0:
        parser.error("max-lines and limit must be positive; context values must be non-negative")

    text, encoding, bom = read_source(args.source)
    lines = text.splitlines()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    chunk_count = 0
    if args.mode in {"chunks", "both"}:
        chunk_count = write_chunks(args.output_dir, args.prefix, args.source, lines, args.max_lines)
        write_index(args.output_dir, args.prefix, args.source, lines, encoding, bom, chunk_count)

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
    if chunk_count:
        print(f"chunks: {chunk_count}")
    if args.mode in {"forensic", "both"}:
        print(f"forensic: {args.prefix}_{args.source.stem}_forensic.txt")


if __name__ == "__main__":
    main()
