#!/usr/bin/env python3
"""
Analyze whitespace / paragraph-like patterns in Chinese TXT files.

Usage:
    python analyze_txt_whitespace.py source-a.txt source-b.txt
    python analyze_txt_whitespace.py hlm.txt --detailed-output output_detailed.txt

This script is read-only:
- It never modifies source files.
- It reports whitespace characteristics.
- It does NOT attempt to infer or rewrite paragraphs.
"""

from __future__ import annotations

import argparse
import codecs
from collections import Counter
from pathlib import Path
from typing import Iterable, TextIO

IDEOGRAPHIC_SPACE = "\u3000"
WHITESPACE_CHARS = " \t\u3000"
TARGET_TRANSITIONS = {
    ("U+3000x2", "ASCII_SPACE_x4"),
    ("ASCII_SPACE_x4", "NO_INDENT"),
    ("NO_INDENT", "U+3000x2"),
}
TARGET_BLANK_RUNS = {5, 8}


def detect_encoding(path: Path) -> tuple[str, bool]:
    raw = path.read_bytes()
    if raw.startswith(codecs.BOM_UTF8):
        return "utf-8-sig", True
    if raw.startswith(codecs.BOM_UTF16_LE):
        return "utf-16-le", True
    if raw.startswith(codecs.BOM_UTF16_BE):
        return "utf-16-be", True
    for encoding in ("utf-8", "gb18030", "big5", "cp950"):
        try:
            raw.decode(encoding)
            return encoding, False
        except UnicodeDecodeError:
            pass
    return "utf-8", False


def read_text(path: Path) -> tuple[str, str, bool]:
    encoding, has_bom = detect_encoding(path)
    raw = path.read_bytes()
    try:
        text = raw.decode(encoding)
    except UnicodeDecodeError:
        encoding = f"{encoding} (errors=replace)"
        text = raw.decode(encoding.split()[0], errors="replace")
    return text, encoding, has_bom


def normalize_newlines_for_analysis(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def leading_whitespace(line: str) -> str:
    i = 0
    while i < len(line) and line[i] in WHITESPACE_CHARS:
        i += 1
    return line[:i]


def leading_category(line: str) -> str:
    if line == "":
        return "EMPTY"
    ws = leading_whitespace(line)
    if not ws:
        return "NO_INDENT"
    if set(ws) == {IDEOGRAPHIC_SPACE}:
        return f"U+3000x{len(ws)}"
    if set(ws) == {" "}:
        return f"ASCII_SPACE_x{len(ws)}"
    if set(ws) == {"\t"}:
        return f"TABx{len(ws)}"
    return "MIXED"


def is_blank(line: str) -> bool:
    return line.strip(WHITESPACE_CHARS) == ""


def indent_signature(line: str) -> str:
    ws = leading_whitespace(line)
    if not ws:
        return "none"
    counts = Counter(ws)
    parts = []
    if counts[IDEOGRAPHIC_SPACE]:
        parts.append(f"U+3000={counts[IDEOGRAPHIC_SPACE]}")
    if counts[" "]:
        parts.append(f"space={counts[' ']}")
    if counts["\t"]:
        parts.append(f"tab={counts['\t']}")
    return ", ".join(parts)


def physical_kind(line: str) -> str:
    if is_blank(line):
        return "BLANK"
    ws = leading_whitespace(line)
    if ws == "\u3000\u3000":
        return "U+3000x2"
    if ws == "    ":
        return "ASCII_SPACE_x4"
    if ws == "":
        return "NO_INDENT"
    return indent_signature(line)


def visible_line(line: str, max_chars: int = 120) -> str:
    escaped = (
        line.replace("\\", "\\\\")
        .replace("\t", "\\t")
        .replace(IDEOGRAPHIC_SPACE, "␠")
    )
    return escaped if len(escaped) <= max_chars else escaped[:max_chars] + "…"


def get_blank_run_lengths(lines: list[str]) -> Counter[int]:
    runs: Counter[int] = Counter()
    current = 0
    for line in lines:
        if is_blank(line):
            current += 1
        elif current:
            runs[current] += 1
            current = 0
    if current:
        runs[current] += 1
    return runs


def get_nonblank_indent_stats(lines: Iterable[str]) -> dict[str, Counter]:
    categories = Counter()
    signatures = Counter()
    for line in lines:
        if not is_blank(line):
            categories[leading_category(line)] += 1
            signatures[indent_signature(line)] += 1
    return {"categories": categories, "signatures": signatures}


def transition_stats(lines: list[str]) -> Counter[tuple[str, str]]:
    result: Counter[tuple[str, str]] = Counter()
    previous: str | None = None
    for line in lines:
        if is_blank(line):
            continue
        current = leading_category(line)
        if previous is not None:
            result[(previous, current)] += 1
        previous = current
    return result


def transition_stats_with_blank(lines: list[str]) -> Counter[tuple[str, str]]:
    result: Counter[tuple[str, str]] = Counter()
    previous: str | None = None
    for line in lines:
        current = "BLANK" if is_blank(line) else leading_category(line)
        if previous is not None:
            result[(previous, current)] += 1
        previous = current
    return result


def print_counter(counter: Counter, *, indent: str = "  ", limit: int | None = None) -> None:
    items = counter.most_common(limit)
    if not items:
        print(indent + "(none)")
        return
    for key, value in items:
        print(f"{indent}{key}: {value}")


def print_transition_counter(counter: Counter[tuple[str, str]], *, limit: int | None = None) -> None:
    items = counter.most_common(limit)
    if not items:
        print("  (none)")
        return
    for (a, b), count in items:
        print(f"  {a:20s} -> {b:20s}: {count}")


def find_examples(lines: list[str], context_limit: int) -> dict[str, list[tuple[int, str, str]]]:
    targets = {
        "U+3000 -> NO_INDENT": [],
        "NO_INDENT -> U+3000": [],
        "U+3000 -> U+3000": [],
        "MIXED": [],
    }
    for i in range(1, len(lines)):
        previous, current = lines[i - 1], lines[i]
        if is_blank(previous) or is_blank(current):
            continue
        prev_cat, curr_cat = leading_category(previous), leading_category(current)
        if prev_cat.startswith("U+3000") and curr_cat == "NO_INDENT" and len(targets["U+3000 -> NO_INDENT"]) < context_limit:
            targets["U+3000 -> NO_INDENT"].append((i + 1, previous, current))
        if prev_cat == "NO_INDENT" and curr_cat.startswith("U+3000") and len(targets["NO_INDENT -> U+3000"]) < context_limit:
            targets["NO_INDENT -> U+3000"].append((i + 1, previous, current))
        if prev_cat.startswith("U+3000") and curr_cat.startswith("U+3000") and len(targets["U+3000 -> U+3000"]) < context_limit:
            targets["U+3000 -> U+3000"].append((i + 1, previous, current))
        if curr_cat == "MIXED" and len(targets["MIXED"]) < context_limit:
            targets["MIXED"].append((i + 1, previous, current))
    return targets


def print_examples(examples: dict[str, list[tuple[int, str, str]]]) -> None:
    for name, rows in examples.items():
        print()
        print(f"--- Examples: {name} ---")
        if not rows:
            print("  (none)")
            continue
        for line_no, previous, current in rows:
            print(f"  line {line_no - 1}: {visible_line(previous)}")
            print(f"  line {line_no}:     {visible_line(current)}")
            print()


def collect_transition_events(lines: list[str], max_events: int) -> dict[tuple[str, str], list[int]]:
    events = {key: [] for key in TARGET_TRANSITIONS}
    previous_kind: str | None = None
    for i, line in enumerate(lines):
        current_kind = physical_kind(line)
        if previous_kind is not None:
            key = (previous_kind, current_kind)
            if key in events and len(events[key]) < max_events:
                events[key].append(i)
        previous_kind = current_kind
    return events


def collect_blank_runs(lines: list[str], target_lengths: set[int], max_events: int) -> dict[int, list[tuple[int, int]]]:
    events = {length: [] for length in target_lengths}
    i = 0
    while i < len(lines):
        if not is_blank(lines[i]):
            i += 1
            continue
        start = i
        while i < len(lines) and is_blank(lines[i]):
            i += 1
        length = i - start
        if length in events and len(events[length]) < max_events:
            events[length].append((start, i))
    return events


def write_context(out: TextIO, lines: list[str], start: int, end: int, highlight: set[int]) -> None:
    for j in range(start, end):
        marker = ">>" if j in highlight else "  "
        out.write(
            f"{marker} {j + 1:6d} {physical_kind(lines[j]):18s} {lines[j].rstrip(chr(13) + chr(10))!r}\n"
        )


def write_detailed_report(
    out: TextIO,
    path: Path,
    lines: list[str],
    context_before: int,
    context_after: int,
    max_events: int,
) -> None:
    """Write targeted forensic evidence without dumping the whole source."""
    transition_events = collect_transition_events(lines, max_events)
    blank_events = collect_blank_runs(lines, TARGET_BLANK_RUNS, max_events)

    out.write("=" * 80 + "\n")
    out.write(f"DETAILED WHITESPACE EVIDENCE: {path}\n")
    out.write("=" * 80 + "\n")
    out.write("This report contains targeted contexts only; it does not infer paragraph semantics.\n")
    out.write(f"context before: {context_before}\n")
    out.write(f"context after:  {context_after}\n")
    out.write(f"max events/category: {max_events}\n")

    out.write("\n")
    out.write("--- TARGET TRANSITIONS ---\n")
    for transition in sorted(TARGET_TRANSITIONS):
        indices = transition_events[transition]
        out.write("\n")
        out.write(f"[{transition[0]} -> {transition[1]}]  count shown: {len(indices)}\n")
        for occurrence, i in enumerate(indices, 1):
            start = max(0, i - context_before - 1)
            end = min(len(lines), i + context_after + 1)
            out.write(f"\nCASE T{occurrence:02d}  transition at lines {i} -> {i + 1}\n")
            out.write("-" * 80 + "\n")
            write_context(out, lines, start, end, {i - 1, i})

    out.write("\n")
    out.write("--- TARGET BLANK RUNS ---\n")
    for length in sorted(TARGET_BLANK_RUNS):
        runs = blank_events[length]
        out.write("\n")
        out.write(f"[BLANK RUN x{length}]  count shown: {len(runs)}\n")
        for occurrence, (start_blank, end_blank) in enumerate(runs, 1):
            start = max(0, start_blank - context_before)
            end = min(len(lines), end_blank + context_after)
            out.write(
                f"\nCASE B{occurrence:02d}  blank lines {start_blank + 1}-{end_blank}\n"
            )
            out.write("-" * 80 + "\n")
            write_context(out, lines, start, end, set(range(start_blank, end_blank)))


def analyze_file(path: Path, context_limit: int, detailed_output: TextIO | None = None) -> None:
    print()
    print("=" * 80)
    print(f"FILE: {path}")
    print("=" * 80)
    try:
        text, encoding, has_bom = read_text(path)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return

    text = normalize_newlines_for_analysis(text)
    lines = text.split("\n")
    nonblank_lines = [line for line in lines if not is_blank(line)]
    blank_lines = [line for line in lines if is_blank(line)]

    print(f"encoding:       {encoding}")
    print(f"BOM:             {'yes' if has_bom else 'no'}")
    print(f"lines:           {len(lines)}")
    print(f"nonblank lines:  {len(nonblank_lines)}")
    print(f"blank lines:     {len(blank_lines)}")

    print()
    print("--- Newline / physical-line information ---")
    raw_bytes = path.read_bytes()
    crlf_count = raw_bytes.count(b"\r\n")
    cr_count = raw_bytes.count(b"\r") - crlf_count
    lf_count = raw_bytes.count(b"\n") - crlf_count
    print(f"CRLF: {crlf_count}")
    print(f"LF:   {lf_count}")
    print(f"CR:   {cr_count}")

    print()
    print("--- Leading whitespace categories ---")
    indent_stats = get_nonblank_indent_stats(lines)
    print_counter(indent_stats["categories"])

    print()
    print("--- Leading whitespace signatures ---")
    print_counter(indent_stats["signatures"], limit=30)

    print()
    print("--- Leading whitespace character counts ---")
    leading_u3000 = leading_ascii_space = leading_tab = mixed = 0
    for line in nonblank_lines:
        ws = leading_whitespace(line)
        leading_u3000 += ws.count(IDEOGRAPHIC_SPACE)
        leading_ascii_space += ws.count(" ")
        leading_tab += ws.count("\t")
        if len(set(ws)) > 1:
            mixed += 1
    print(f"U+3000 in leading whitespace: {leading_u3000}")
    print(f"ASCII spaces in leading whitespace: {leading_ascii_space}")
    print(f"TABs in leading whitespace: {leading_tab}")
    print(f"mixed-leading-whitespace lines: {mixed}")

    print()
    print("--- U+3000 outside leading whitespace ---")
    trailing_u3000 = internal_u3000 = 0
    for line in lines:
        ws = leading_whitespace(line)
        rest = line[len(ws):]
        trailing_count = len(line) - len(line.rstrip(IDEOGRAPHIC_SPACE))
        trailing_u3000 += trailing_count
        internal_count = rest.count(IDEOGRAPHIC_SPACE) - trailing_count
        internal_u3000 += max(internal_count, 0)
    print(f"trailing U+3000 characters: {trailing_u3000}")
    print(f"internal U+3000 characters: {internal_u3000}")

    print()
    print("--- Blank-line runs ---")
    blank_runs = get_blank_run_lengths(lines)
    if not blank_runs:
        print("  (none)")
    else:
        for run_length, count in sorted(blank_runs.items()):
            print(f"  {run_length} consecutive blank line(s): {count}")

    print()
    print("--- Indentation transitions (blank lines skipped) ---")
    print_transition_counter(transition_stats(lines), limit=30)

    print()
    print("--- Physical-line transitions (blank lines included) ---")
    print_transition_counter(transition_stats_with_blank(lines), limit=40)

    print_examples(find_examples(lines, context_limit))

    print()
    print("--- Mixed / unusual indentation samples ---")
    unusual_count = 0
    for i, line in enumerate(lines, start=1):
        if is_blank(line):
            continue
        category = leading_category(line)
        if category == "MIXED" or (category.startswith("U+3000") and len(leading_whitespace(line)) not in {1, 2}):
            print(f"  line {i:>7}: {category:15s} [{indent_signature(line)}] {visible_line(line)}")
            unusual_count += 1
            if unusual_count >= context_limit:
                break
    if unusual_count == 0:
        print("  (none)")

    if detailed_output is not None:
        write_detailed_report(
            detailed_output,
            path,
            lines,
            context_before=5,
            context_after=5,
            max_events=context_limit,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze whitespace patterns in Chinese TXT files.")
    parser.add_argument("files", nargs="+", type=Path, help="TXT files to analyze")
    parser.add_argument("--context-limit", type=int, default=20, help="Maximum detailed cases per category (default: 20)")
    parser.add_argument(
        "--detailed-output",
        type=Path,
        help="Write targeted forensic contexts to this file; stdout remains the compact summary",
    )
    args = parser.parse_args()

    detailed_output = None
    try:
        if args.detailed_output is not None:
            detailed_output = args.detailed_output.open("w", encoding="utf-8")
            detailed_output.write("# Targeted whitespace evidence\n")

        for path in args.files:
            if not path.exists():
                print(f"ERROR: file not found: {path}")
                continue
            if not path.is_file():
                print(f"ERROR: not a file: {path}")
                continue
            analyze_file(path, args.context_limit, detailed_output)
    finally:
        if detailed_output is not None:
            detailed_output.close()


if __name__ == "__main__":
    main()
