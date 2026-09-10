#!/usr/bin/env python3
"""
Analyze whitespace / paragraph-like patterns in Chinese TXT files.

Usage:
    python analyze_txt_whitespace.py source-a.txt source-b.txt

Optional:
    python analyze_txt_whitespace.py *.txt --context-limit 20

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
from typing import Iterable


IDEOGRAPHIC_SPACE = "\u3000"
WHITESPACE_CHARS = " \t\u3000"


def detect_encoding(path: Path) -> tuple[str, bool]:
    """Best-effort encoding detection for common Chinese TXT encodings."""
    raw = path.read_bytes()

    if raw.startswith(codecs.BOM_UTF8):
        return "utf-8-sig", True

    if raw.startswith(codecs.BOM_UTF16_LE):
        return "utf-16-le", True

    if raw.startswith(codecs.BOM_UTF16_BE):
        return "utf-16-be", True

    candidates = [
        "utf-8",
        "gb18030",
        "big5",
        "cp950",
    ]

    for encoding in candidates:
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
        # Last-resort diagnostic decode. We explicitly report this later.
        encoding = f"{encoding} (errors=replace)"
        text = raw.decode(encoding.split()[0], errors="replace")

    return text, encoding, has_bom


def normalize_newlines_for_analysis(text: str) -> str:
    """Only normalize newline representation for analysis."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def leading_whitespace(line: str) -> str:
    """Return only leading ASCII spaces, tabs and U+3000."""
    i = 0
    while i < len(line) and line[i] in WHITESPACE_CHARS:
        i += 1
    return line[:i]


def leading_category(line: str) -> str:
    """
    Classify the beginning of a physical line.

    Categories intentionally preserve distinctions useful for this investigation.
    """
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
    """
    Blank means the line contains only whitespace.

    Deliberately broader than normalize_line():
    ASCII spaces, tabs and U+3000 all count as blank.
    """
    return line.strip(WHITESPACE_CHARS) == ""


def indent_signature(line: str) -> str:
    """Return a compact representation of leading whitespace."""
    ws = leading_whitespace(line)

    if not ws:
        return "none"

    counts = Counter(ws)

    ideographic_space = "\u3000"
    tab = "\t"
    ascii_space = " "

    parts = []

    if counts[ideographic_space]:
        n = counts[ideographic_space]
        parts.append(f"U+3000={n}")

    if counts[ascii_space]:
        n = counts[ascii_space]
        parts.append(f"space={n}")

    if counts[tab]:
        n = counts[tab]
        parts.append(f"tab={n}")

    return ", ".join(parts)

def physical_kind(line: str) -> str:
    if not line.strip():
        return "BLANK"

    ws = leading_whitespace(line)

    if ws == "\u3000\u3000":
        return "U+3000x2"
    if ws == "    ":
        return "ASCII_SPACE_x4"
    if ws == "":
        return "NO_INDENT"

    return indent_signature(line)


def print_transition_contexts(
    lines: list[str],
    transitions: set[tuple[str, str]],
    context: int = 3,
    max_per_transition: int = 20,
) -> None:
    print()
    print("=" * 80)
    print("TRANSITION CONTEXTS")
    print("=" * 80)

    hits: dict[tuple[str, str], int] = {
        transition: 0 for transition in transitions
    }

    previous_kind = None

    for i, line in enumerate(lines):
        current_kind = physical_kind(line)

        if previous_kind is not None:
            transition = (previous_kind, current_kind)

            if transition in transitions:
                if hits[transition] >= max_per_transition:
                    previous_kind = current_kind
                    continue

                hits[transition] += 1

                start = max(0, i - context - 1)
                end = min(len(lines), i + context + 2)

                print()
                print(
                    f"[{transition[0]} -> {transition[1]}]"
                    f"  occurrence #{hits[transition]}"
                    f"  around line {i + 1}"
                )
                print("-" * 80)

                for j in range(start, end):
                    marker = ">>" if j in (i - 1, i) else "  "
                    text = lines[j].rstrip("\r\n")

                    print(
                        f"{marker} {j + 1:6d} "
                        f"{physical_kind(lines[j]):18s} "
                        f"{text!r}"
                    )

        previous_kind = current_kind

    print()
    print("Summary:")
    for transition, count in hits.items():
        print(f"  {transition[0]:18s} -> {transition[1]:18s}: {count}")


def print_blank_run_contexts(
    lines: list[str],
    target_lengths: set[int],
    context: int = 3,
    max_per_length: int = 20,
) -> None:
    print()
    print("=" * 80)
    print("BLANK-RUN CONTEXTS")
    print("=" * 80)

    hits = {length: 0 for length in target_lengths}

    i = 0

    while i < len(lines):
        if lines[i].strip():
            i += 1
            continue

        start_blank = i

        while i < len(lines) and not lines[i].strip():
            i += 1

        length = i - start_blank

        if length not in target_lengths:
            continue

        if hits[length] >= max_per_length:
            continue

        hits[length] += 1

        start = max(0, start_blank - context)
        end = min(len(lines), i + context)

        print()
        print(
            f"[BLANK RUN x{length}]"
            f"  occurrence #{hits[length]}"
            f"  starts at line {start_blank + 1}"
        )
        print("-" * 80)

        for j in range(start, end):
            marker = (
                ">>"
                if start_blank <= j < i
                else "  "
            )

            text = lines[j].rstrip("\r\n")

            print(
                f"{marker} {j + 1:6d} "
                f"{physical_kind(lines[j]):18s} "
                f"{text!r}"
            )

    print()
    print("Summary:")
    for length, count in hits.items():
        print(f"  blank run x{length}: {count}")

def visible_line(line: str, max_chars: int = 100) -> str:
    """
    Make whitespace visible without dumping too much source text.
    """
    escaped = (
        line
        .replace("\\", "\\\\")
        .replace("\t", "\\t")
        .replace("\u3000", "␠")
    )

    if len(escaped) > max_chars:
        return escaped[:max_chars] + "…"

    return escaped


def get_blank_run_lengths(lines: list[str]) -> Counter[int]:
    runs: Counter[int] = Counter()
    current = 0

    for line in lines:
        if is_blank(line):
            current += 1
        else:
            if current:
                runs[current] += 1
                current = 0

    if current:
        runs[current] += 1

    return runs


def get_nonblank_indent_stats(lines: Iterable[str]) -> dict[str, Counter]:
    categories = Counter()
    signatures = Counter()

    for line in lines:
        if is_blank(line):
            continue

        categories[leading_category(line)] += 1
        signatures[indent_signature(line)] += 1

    return {
        "categories": categories,
        "signatures": signatures,
    }


def transition_stats(lines: list[str]) -> Counter[tuple[str, str]]:
    """
    Count transitions between consecutive nonblank physical lines.

    Blank lines are skipped here.

    This answers questions such as:
        U+3000 -> U+3000
        U+3000 -> NO_INDENT
        NO_INDENT -> U+3000

    without treating blank lines as indentation transitions.
    """
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
    """
    Same as transition_stats(), but keeps blank lines as a category.

    Consecutive blank lines are represented individually as BLANK.
    """
    result: Counter[tuple[str, str]] = Counter()

    previous: str | None = None

    for line in lines:
        current = "BLANK" if is_blank(line) else leading_category(line)

        if previous is not None:
            result[(previous, current)] += 1

        previous = current

    return result


def find_examples(
    lines: list[str],
    context_limit: int,
) -> dict[str, list[tuple[int, str, str]]]:
    """
    Find concrete examples for the important transition patterns.

    Returned line number is 1-based and points to the second line
    in the transition.
    """
    targets = {
        "U+3000 -> NO_INDENT": [],
        "NO_INDENT -> U+3000": [],
        "U+3000 -> U+3000": [],
        "MIXED": [],
    }

    for i in range(1, len(lines)):
        previous = lines[i - 1]
        current = lines[i]

        if is_blank(previous) or is_blank(current):
            continue

        prev_cat = leading_category(previous)
        curr_cat = leading_category(current)

        if (
            prev_cat.startswith("U+3000")
            and curr_cat == "NO_INDENT"
            and len(targets["U+3000 -> NO_INDENT"]) < context_limit
        ):
            targets["U+3000 -> NO_INDENT"].append(
                (i + 1, previous, current)
            )

        if (
            prev_cat == "NO_INDENT"
            and curr_cat.startswith("U+3000")
            and len(targets["NO_INDENT -> U+3000"]) < context_limit
        ):
            targets["NO_INDENT -> U+3000"].append(
                (i + 1, previous, current)
            )

        if (
            prev_cat.startswith("U+3000")
            and curr_cat.startswith("U+3000")
            and len(targets["U+3000 -> U+3000"]) < context_limit
        ):
            targets["U+3000 -> U+3000"].append(
                (i + 1, previous, current)
            )

        if (
            curr_cat == "MIXED"
            and len(targets["MIXED"]) < context_limit
        ):
            targets["MIXED"].append(
                (i + 1, previous, current)
            )

    return targets


def print_counter(
    counter: Counter,
    *,
    indent: str = "  ",
    limit: int | None = None,
) -> None:
    items = counter.most_common(limit)

    if not items:
        print(indent + "(none)")
        return

    for key, value in items:
        print(f"{indent}{key}: {value}")


def print_transition_counter(
    counter: Counter[tuple[str, str]],
    *,
    limit: int | None = None,
) -> None:
    items = counter.most_common(limit)

    if not items:
        print("  (none)")
        return

    for (a, b), count in items:
        print(f"  {a:20s} -> {b:20s}: {count}")


def print_examples(
    examples: dict[str, list[tuple[int, str, str]]],
) -> None:
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


def analyze_file(path: Path, context_limit: int) -> None:
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

    # ------------------------------------------------------------
    # Newline information
    # ------------------------------------------------------------

    print()
    print("--- Newline / physical-line information ---")

    raw_bytes = path.read_bytes()

    crlf_count = raw_bytes.count(b"\r\n")
    cr_count = raw_bytes.count(b"\r") - crlf_count
    lf_count = raw_bytes.count(b"\n") - crlf_count

    print(f"CRLF: {crlf_count}")
    print(f"LF:   {lf_count}")
    print(f"CR:   {cr_count}")

    # ------------------------------------------------------------
    # Indentation categories
    # ------------------------------------------------------------

    print()
    print("--- Leading whitespace categories ---")

    indent_stats = get_nonblank_indent_stats(lines)

    print_counter(indent_stats["categories"])

    # ------------------------------------------------------------
    # Exact leading whitespace signatures
    # ------------------------------------------------------------

    print()
    print("--- Leading whitespace signatures ---")

    print_counter(indent_stats["signatures"], limit=30)

    # ------------------------------------------------------------
    # Character-level counts
    # ------------------------------------------------------------

    print()
    print("--- Leading whitespace character counts ---")

    leading_u3000 = 0
    leading_ascii_space = 0
    leading_tab = 0
    mixed = 0

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

    # ------------------------------------------------------------
    # Internal / trailing U+3000
    # ------------------------------------------------------------

    print()
    print("--- U+3000 outside leading whitespace ---")

    trailing_u3000 = 0
    internal_u3000 = 0

    for line in lines:
        ws = leading_whitespace(line)
        rest = line[len(ws):]

        trailing_count = len(line) - len(line.rstrip(IDEOGRAPHIC_SPACE))
        trailing_u3000 += trailing_count

        internal_count = rest.count(IDEOGRAPHIC_SPACE) - trailing_count
        internal_u3000 += max(internal_count, 0)

    print(f"trailing U+3000 characters: {trailing_u3000}")
    print(f"internal U+3000 characters: {internal_u3000}")

    # ------------------------------------------------------------
    # Blank lines
    # ------------------------------------------------------------

    print()
    print("--- Blank-line runs ---")

    blank_runs = get_blank_run_lengths(lines)

    if not blank_runs:
        print("  (none)")
    else:
        for run_length, count in sorted(blank_runs.items()):
            print(f"  {run_length} consecutive blank line(s): {count}")

    # ------------------------------------------------------------
    # Transitions without blank lines
    # ------------------------------------------------------------

    print()
    print("--- Indentation transitions (blank lines skipped) ---")

    transitions = transition_stats(lines)
    print_transition_counter(transitions, limit=30)

    # ------------------------------------------------------------
    # Transitions including blank lines
    # ------------------------------------------------------------

    print()
    print("--- Physical-line transitions (blank lines included) ---")

    transitions_with_blank = transition_stats_with_blank(lines)
    print_transition_counter(transitions_with_blank, limit=40)

    # ------------------------------------------------------------
    # Concrete examples
    # ------------------------------------------------------------

    examples = find_examples(lines, context_limit)
    print_examples(examples)

    # ------------------------------------------------------------
    # First few suspicious lines
    # ------------------------------------------------------------

    print()
    print("--- Mixed / unusual indentation samples ---")

    unusual_count = 0

    for i, line in enumerate(lines, start=1):
        if is_blank(line):
            continue

        category = leading_category(line)

        if category in {"MIXED"} or (
            category.startswith("U+3000")
            and len(leading_whitespace(line)) not in {1, 2}
        ):
            print(
                f"  line {i:>7}: "
                f"{category:15s} "
                f"[{indent_signature(line)}] "
                f"{visible_line(line)}"
            )

            unusual_count += 1

            if unusual_count >= context_limit:
                break

    if unusual_count == 0:
        print("  (none)")

    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze whitespace patterns in Chinese TXT files."
    )

    parser.add_argument(
        "files",
        nargs="+",
        type=Path,
        help="TXT files to analyze",
    )

    parser.add_argument(
        "--context-limit",
        type=int,
        default=20,
        help="Maximum examples per transition category (default: 20)",
    )

    args = parser.parse_args()

    for path in args.files:
        if not path.exists():
            print(f"ERROR: file not found: {path}")
            continue

        if not path.is_file():
            print(f"ERROR: not a file: {path}")
            continue

        analyze_file(path, args.context_limit)
    print_transition_contexts(
        lines,
        {
            ("U+3000x2", "ASCII_SPACE_x4"),
            ("ASCII_SPACE_x4", "NO_INDENT"),
            ("NO_INDENT", "U+3000x2"),
        },
        context=3,
        max_per_transition=20,
    )

    print_blank_run_contexts(
        lines,
        {
            5,
            8,
        },
        context=3,
        max_per_length=20,
    )


if __name__ == "__main__":
    main()