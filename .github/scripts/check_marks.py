#!/usr/bin/env python3
"""Check every mark of the contracts of this repository against the mark list.

The mark list, `marks.json5` at the root of the repository, names each mark
that a contract can give, with its owner and its meaning. The script reads
the list and refuses a malformed one. It then reads every contract document
of the repository: each `.json5` file outside the hidden directories, such
as `.github`, whose `peppy_schema` is `contract/v1`. It collects each member
mark (`marks` on a topic, a service or an action) and each field mark
(`$marks` on a field of a message format, through objects, arrays and array
items). It exits 1 with one line for each mark that the list does not name,
and 0 with a short summary otherwise.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
from typing import Iterator

import json5

MARK_LIST_FILE = "marks.json5"
CONTRACT_SCHEMA = "contract/v1"
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

# The rule of mark names, as peppy parses them: words of lowercase ASCII
# letters and digits that each start with a letter, joined by one `_`.
MAX_MARK_NAME_BYTES = 64
MARK_NAME_CHARACTERS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_")

MARK_ENTRY_KEYS = ("name", "owner", "meaning")

# Each section of `interfaces`, the kind of its members, and the message
# formats of such a member, each by its keys in the member.
MEMBER_SECTIONS = (
    ("topics", "topic", (("message_format",),)),
    ("services", "service", (("request_message_format",), ("response_message_format",))),
    (
        "actions",
        "action",
        (
            ("goal_service", "request_message_format"),
            ("goal_service", "response_message_format"),
            ("feedback_topic", "message_format"),
            ("result_service", "response_message_format"),
        ),
    ),
)


class MarkListError(Exception):
    """The mark list is not a list of marks: each problem it has."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class MarkDefinition:
    """One entry of the mark list."""

    name: str
    owner: str
    meaning: str


@dataclass(frozen=True)
class MarkSite:
    """A list of marks as a contract writes it: on a member or on a field."""

    # The path of the contract document, relative to the repository root.
    path: str
    # "topic", "service" or "action".
    member_kind: str
    member_name: str
    # The path of the field in the member, such as
    # `response_message_format.results[].arm`; `[]` stands for the items of
    # an array. None for the marks of the member.
    field: str | None
    # The value of `marks` or `$marks`, as written.
    marks: object

    def location(self) -> str:
        where = f"{self.path}: {self.member_kind} {self.member_name}"
        if self.field is None:
            return where
        return f"{where}, field {self.field}"


@dataclass(frozen=True)
class CheckResult:
    """What a check of a repository found."""

    # One line for each problem; empty when the check passes.
    problems: list[str]
    contracts: int = 0
    marks: int = 0
    listed_marks: int = 0


def mark_name_problem(name: str) -> str | None:
    """Why `name` breaks the rule of mark names, or None when it is a name."""
    if not name:
        return "it is empty"
    if len(name.encode("utf-8")) > MAX_MARK_NAME_BYTES:
        return f"it is longer than {MAX_MARK_NAME_BYTES} bytes"
    if not set(name) <= MARK_NAME_CHARACTERS:
        return "it may hold only lowercase ASCII letters, digits and `_`"
    if not all(word[:1].isalpha() for word in name.split("_")):
        return "it must be words that each start with a lowercase ASCII letter, joined by one `_`"
    return None


def quoted(value: object) -> str:
    """`value` in JSON, so that each problem stays on one line."""
    return json.dumps(value, ensure_ascii=False)


def parse_mark_entry(entry: object, where: str) -> tuple[MarkDefinition | None, list[str]]:
    """The definition that one entry of the mark list gives, and its problems."""
    if not isinstance(entry, dict):
        return None, [f"{where} is not an object"]
    problems = [f"{where} has no `{key}`" for key in MARK_ENTRY_KEYS if key not in entry]
    problems += [
        f"{where} has the unknown key {quoted(key)}" for key in entry if key not in MARK_ENTRY_KEYS
    ]
    name = entry.get("name")
    if "name" in entry:
        if not isinstance(name, str):
            problems.append(f"{where}: `name` is not a string")
        elif (reason := mark_name_problem(name)) is not None:
            problems.append(f"{where}: {quoted(name)} is not a mark name: {reason}")
    for key in ("owner", "meaning"):
        value = entry.get(key)
        if key in entry and (not isinstance(value, str) or not value.strip()):
            problems.append(f"{where}: `{key}` is not a non-empty string")
    if problems:
        return None, problems
    return MarkDefinition(name=name, owner=entry["owner"], meaning=entry["meaning"]), []


def parse_mark_list(document: object) -> dict[str, MarkDefinition]:
    """The marks of the list, by name. Raises MarkListError with each problem."""
    if not isinstance(document, dict) or set(document) != {"marks"}:
        raise MarkListError(["the document is not an object with the one key `marks`"])
    entries = document["marks"]
    if not isinstance(entries, list):
        raise MarkListError(["`marks` is not a list"])
    definitions: dict[str, MarkDefinition] = {}
    problems: list[str] = []
    for index, entry in enumerate(entries, start=1):
        where = f"entry {index} of `marks`"
        definition, entry_problems = parse_mark_entry(entry, where)
        problems += entry_problems
        if definition is None:
            continue
        if definition.name in definitions:
            problems.append(f"{where}: mark {quoted(definition.name)} is in the list twice")
            continue
        definitions[definition.name] = definition
    if problems:
        raise MarkListError(problems)
    return definitions


def read_json5(path: Path) -> object:
    return json5.loads(path.read_text(encoding="utf-8"), allow_duplicate_keys=False)


def read_mark_list(path: Path) -> dict[str, MarkDefinition]:
    """The marks of the list file at `path`. Raises MarkListError."""
    try:
        document = read_json5(path)
    except (OSError, ValueError, RecursionError) as error:
        raise MarkListError([f"cannot read it: {error}"]) from error
    return parse_mark_list(document)


def json5_files(root: Path) -> list[Path]:
    """Every `.json5` file under `root` outside the hidden directories, sorted."""
    files: list[Path] = []
    for directory, subdirectories, names in os.walk(root):
        subdirectories[:] = sorted(name for name in subdirectories if not name.startswith("."))
        files += (
            Path(directory, name)
            for name in names
            if not name.startswith(".") and name.lower().endswith(".json5")
        )
    return sorted(files, key=lambda path: path.relative_to(root).as_posix())


def field_mark_sites(schema: object, field: str) -> Iterator[tuple[str, object]]:
    """Each field path in `schema` that has `$marks`, with its marks as written.

    `schema` is a message format or a field of one. The walk goes through
    the fields of objects and the `$items` of arrays.
    """
    if not isinstance(schema, dict):
        return
    if "$marks" in schema:
        yield field, schema["$marks"]
    for key, value in schema.items():
        if key == "$items":
            yield from field_mark_sites(value, f"{field}[]")
        elif not key.startswith("$"):
            yield from field_mark_sites(value, f"{field}.{key}")


def nested(value: object, keys: tuple[str, ...]) -> object:
    """The value at `keys` in nested objects, or None when there is none."""
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def contract_mark_sites(document: dict, path: str) -> list[MarkSite]:
    """Each list of marks of the contract document `document`, in its order."""
    interfaces = document.get("interfaces")
    if not isinstance(interfaces, dict):
        return []
    sites: list[MarkSite] = []
    for section, kind, formats in MEMBER_SECTIONS:
        members = interfaces.get(section)
        if not isinstance(members, list):
            continue
        for index, member in enumerate(members, start=1):
            if not isinstance(member, dict):
                continue
            name = member.get("name")
            member_name = name if isinstance(name, str) else f"#{index}"
            if "marks" in member:
                sites.append(MarkSite(path, kind, member_name, None, member["marks"]))
            for keys in formats:
                schema = nested(member, keys)
                for field, marks in field_mark_sites(schema, ".".join(keys)):
                    sites.append(MarkSite(path, kind, member_name, field, marks))
    return sites


def site_problems(site: MarkSite, listed: dict[str, MarkDefinition]) -> list[str]:
    """One line for each mark of `site` that the list does not name."""
    marks = site.marks
    if not isinstance(marks, list) or not all(isinstance(mark, str) for mark in marks):
        return [f"{site.location()}: the marks are not a list of mark names"]
    return [
        f"{site.location()}: mark {quoted(mark)} is not in the mark list ({MARK_LIST_FILE})"
        for mark in marks
        if mark not in listed
    ]


def check_repository(root: Path) -> CheckResult:
    """Check every mark of the contracts under `root` against its mark list."""
    try:
        listed = read_mark_list(root / MARK_LIST_FILE)
    except MarkListError as error:
        return CheckResult(problems=[f"{MARK_LIST_FILE}: {problem}" for problem in error.problems])

    problems: list[str] = []
    contracts = 0
    marks = 0
    for file in json5_files(root):
        path = file.relative_to(root).as_posix()
        try:
            document = read_json5(file)
        except (OSError, ValueError, RecursionError) as error:
            problems.append(f"{path}: cannot read it: {error}")
            continue
        if not isinstance(document, dict) or document.get("peppy_schema") != CONTRACT_SCHEMA:
            continue
        contracts += 1
        for site in contract_mark_sites(document, path):
            if isinstance(site.marks, list):
                marks += len(site.marks)
            problems += site_problems(site, listed)
    if contracts == 0:
        problems.append(f"found no contract document ({CONTRACT_SCHEMA}) under {root}")
    return CheckResult(problems=problems, contracts=contracts, marks=marks, listed_marks=len(listed))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--root",
        type=Path,
        default=REPOSITORY_ROOT,
        help="the root of the repository (default: the repository of this script)",
    )
    args = parser.parse_args(argv)
    result = check_repository(args.root)
    if result.problems:
        for problem in result.problems:
            print(problem, file=sys.stderr)
        return 1
    print(
        f"Each mark of the contracts is in {MARK_LIST_FILE} (contracts: {result.contracts}, "
        f"marks given: {result.marks}, marks in the list: {result.listed_marks})."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
