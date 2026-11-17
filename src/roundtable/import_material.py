"""Convert one explicit local TXT/MD/CSV/PDF to a locatable material packet.

Use ``python -m roundtable.import_material path --source-id S1 --title TITLE``.
Readiness describes readable text, never factual verification. No OCR, network
access or LLM is used. This entry stays separate from package-imported APIs.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import NoReturn

from roundtable.materials import prepare_material


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        # argparse normally echoes unknown arguments and invalid option values.
        raise ValueError("arguments: expected path, --source-id and --title; optional --format")


def main(argv: list[str] | None = None) -> int:
    """Emit UTF-8 JSON on stdout, or a content-free diagnostic on stderr."""
    parser = _ArgumentParser(prog="python -m roundtable.import_material", description=__doc__, allow_abbrev=False)
    parser.add_argument("path")
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--format")
    try:
        arguments = parser.parse_args(argv)
        packet = prepare_material(
            arguments.path, source_id=arguments.source_id, title=arguments.title, format=arguments.format
        )
        output = json.dumps(packet, ensure_ascii=False, indent=2) + "\n"
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    try:
        binary_stdout = getattr(sys.stdout, "buffer", None)
        if binary_stdout is None:
            sys.stdout.write(output)
        else:
            binary_stdout.write(output.encode("utf-8"))
        sys.stdout.flush()
    except OSError:
        print("material: unable to write JSON", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
