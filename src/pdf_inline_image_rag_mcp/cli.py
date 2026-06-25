from __future__ import annotations

import argparse
import json
import textwrap
from pathlib import Path

from .extractor import build_database, get_page, inspect_database, search_database


def build_cmd(args: argparse.Namespace) -> int:
    result = build_database(
        args.input,
        args.output_dir,
        db_path=args.db,
        pages=args.pages,
        replace=args.replace,
        render_pages=args.render_pages,
        dpi=args.dpi,
        flag_images_for_ocr=args.flag_images_for_ocr,
    )
    print(json.dumps(result, indent=2))
    return 0


def search_cmd(args: argparse.Namespace) -> int:
    rows = search_database(args.db, args.query, args.limit)
    for row in rows:
        print(f"page {row['page_number']} images={row['image_count']} needs_ocr={bool(row['needs_ocr'])}")
        print(textwrap.fill(row["snippet"], width=100))
        print(f"  visual_json: {row['visual_json_path']}")
        print()
    return 0


def page_cmd(args: argparse.Namespace) -> int:
    page = get_page(args.db, args.page_number)
    print(json.dumps(page, indent=2))
    return 0


def inspect_cmd(args: argparse.Namespace) -> int:
    print(json.dumps(inspect_database(args.db, args.limit), indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PDF inline-image RAG database CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="Build a searchable database from a PDF")
    build.add_argument("--input", required=True, type=Path)
    build.add_argument("--output-dir", required=True, type=Path)
    build.add_argument("--db", type=Path)
    build.add_argument("--pages", help="1-based pages or ranges, e.g. 1-5,10,12")
    build.add_argument("--replace", action="store_true", default=True)
    build.add_argument("--no-replace", action="store_false", dest="replace")
    build.add_argument("--render-pages", action="store_true", help="Optional debug whole-page PNGs")
    build.add_argument("--dpi", type=int, default=160)
    build.add_argument("--flag-images-for-ocr", action="store_true", default=True)
    build.add_argument("--no-flag-images-for-ocr", action="store_false", dest="flag_images_for_ocr")
    build.set_defaults(func=build_cmd)

    search = sub.add_parser("search", help="Search an existing database")
    search.add_argument("--db", required=True, type=Path)
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=10)
    search.set_defaults(func=search_cmd)

    page = sub.add_parser("page", help="Return a page record and its images")
    page.add_argument("--db", required=True, type=Path)
    page.add_argument("page_number", type=int)
    page.set_defaults(func=page_cmd)

    inspect = sub.add_parser("inspect", help="Inspect database counts")
    inspect.add_argument("--db", required=True, type=Path)
    inspect.add_argument("--limit", type=int, default=50)
    inspect.set_defaults(func=inspect_cmd)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
