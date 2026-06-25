from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fitz


CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
WS_RE = re.compile(r"\s+")


@dataclass
class PageItem:
    kind: str
    block_number: int
    bbox: tuple[float, float, float, float]
    text: str
    image_index: int | None = None
    image_path: str | None = None
    image_width: int | None = None
    image_height: int | None = None


def clean_text(text: str) -> str:
    text = CONTROL_RE.sub("", text)
    text = text.replace("\u00ad", "")
    text = text.replace("\ufb01", "fi").replace("\ufb02", "fl")
    lines = [WS_RE.sub(" ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "pdf"


def parse_pages(value: str | None, page_count: int) -> list[int]:
    if not value:
        return list(range(page_count))
    pages: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            left, right = part.split("-", 1)
            pages.update(range(int(left) - 1, int(right)))
        else:
            pages.add(int(part) - 1)
    return sorted(page for page in pages if 0 <= page < page_count)


def relative_to_output(path: Path, output_dir: Path) -> str:
    try:
        return str(path.relative_to(output_dir))
    except ValueError:
        return str(path)


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY,
            source_path TEXT NOT NULL,
            title TEXT,
            page_count INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS pages (
            id INTEGER PRIMARY KEY,
            document_id INTEGER NOT NULL REFERENCES documents(id),
            page_number INTEGER NOT NULL,
            width REAL NOT NULL,
            height REAL NOT NULL,
            text TEXT NOT NULL,
            text_with_images TEXT NOT NULL,
            markdown TEXT NOT NULL,
            png_path TEXT,
            visual_json_path TEXT,
            text_char_count INTEGER NOT NULL,
            image_count INTEGER NOT NULL,
            needs_ocr INTEGER NOT NULL,
            UNIQUE(document_id, page_number)
        );

        CREATE TABLE IF NOT EXISTS images (
            id INTEGER PRIMARY KEY,
            page_id INTEGER NOT NULL REFERENCES pages(id),
            image_number INTEGER NOT NULL,
            xref INTEGER,
            width INTEGER,
            height INTEGER,
            colorspace INTEGER,
            bits_per_component INTEGER,
            file_ext TEXT,
            file_path TEXT NOT NULL,
            bbox_x0 REAL,
            bbox_y0 REAL,
            bbox_x1 REAL,
            bbox_y1 REAL,
            block_number INTEGER,
            placeholder TEXT,
            caption TEXT,
            caption_model TEXT,
            caption_created_at TEXT
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
            page_id UNINDEXED,
            source_path UNINDEXED,
            page_number UNINDEXED,
            body,
            tokenize='porter unicode61'
        );
        """
    )
    existing_image_cols = {row[1] for row in conn.execute("PRAGMA table_info(images)")}
    for col, sql in {
        "caption": "ALTER TABLE images ADD COLUMN caption TEXT",
        "caption_model": "ALTER TABLE images ADD COLUMN caption_model TEXT",
        "caption_created_at": "ALTER TABLE images ADD COLUMN caption_created_at TEXT",
    }.items():
        if col not in existing_image_cols:
            conn.execute(sql)


def reset_document(conn: sqlite3.Connection, source_path: Path) -> None:
    rows = conn.execute("SELECT id FROM documents WHERE source_path = ?", (str(source_path),)).fetchall()
    for (doc_id,) in rows:
        page_ids = [row[0] for row in conn.execute("SELECT id FROM pages WHERE document_id = ?", (doc_id,))]
        if page_ids:
            placeholders = ",".join("?" for _ in page_ids)
            conn.execute(f"DELETE FROM images WHERE page_id IN ({placeholders})", page_ids)
            conn.execute(f"DELETE FROM pages_fts WHERE page_id IN ({placeholders})", page_ids)
        conn.execute("DELETE FROM pages WHERE document_id = ?", (doc_id,))
        conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))


def extract_page_items(
    page: fitz.Page,
    page_number: int,
    image_dir: Path,
    output_dir: Path,
) -> tuple[str, str, list[PageItem], list[dict[str, Any]]]:
    raw = page.get_text("dict")
    items: list[PageItem] = []
    image_rows: list[dict[str, Any]] = []
    image_index = 0

    for block in raw.get("blocks", []):
        bbox = tuple(round(float(value), 1) for value in block.get("bbox", [0, 0, 0, 0]))
        block_number = int(block.get("number", len(items)))
        if block.get("type") == 0:
            pieces = []
            for line in block.get("lines", []):
                line_text = "".join(span.get("text", "") for span in line.get("spans", []))
                if line_text.strip():
                    pieces.append(line_text.strip())
            text = clean_text(" ".join(pieces))
            if text:
                items.append(PageItem("text", block_number, bbox, text))
        elif block.get("type") == 1:
            image_bytes = block.get("image")
            if not image_bytes:
                continue
            image_index += 1
            ext = block.get("ext") or "bin"
            out_path = image_dir / f"page_{page_number:04d}_image_{image_index:02d}.{ext}"
            out_path.write_bytes(image_bytes)
            rel_path = relative_to_output(out_path, output_dir)
            placeholder = (
                f"[[IMAGE page={page_number} index={image_index} "
                f"bbox={bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]} "
                f"size={block.get('width')}x{block.get('height')} file={rel_path}]]"
            )
            items.append(
                PageItem(
                    "image",
                    block_number,
                    bbox,
                    placeholder,
                    image_index=image_index,
                    image_path=rel_path,
                    image_width=block.get("width"),
                    image_height=block.get("height"),
                )
            )
            image_rows.append(
                {
                    "image_number": image_index,
                    "xref": block.get("xref"),
                    "width": block.get("width"),
                    "height": block.get("height"),
                    "colorspace": block.get("colorspace"),
                    "bpc": block.get("bpc"),
                    "ext": ext,
                    "file_path": rel_path,
                    "bbox": bbox,
                    "block_number": block_number,
                    "placeholder": placeholder,
                }
            )

    items.sort(key=lambda item: (item.bbox[1], item.bbox[0], item.block_number))
    text = "\n\n".join(item.text for item in items if item.kind == "text")
    text_with_images = "\n\n".join(item.text for item in items)
    return text, text_with_images, items, image_rows


def render_page_png(page: fitz.Page, path: Path, dpi: int) -> None:
    scale = dpi / 72
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    pix.save(str(path))


def write_page_markdown(
    source_name: str,
    page_number: int,
    text: str,
    text_with_images: str,
    png_path: str | None,
    image_rows: list[dict[str, Any]],
) -> str:
    lines = [
        f"## {source_name} - page {page_number}",
        f"<!-- pdf-page: {page_number} -->",
        "",
        "### Extracted Text",
        text if text else "> No embedded text extracted.",
        "",
        "### Text With Inline Image Placeholders",
        text_with_images if text_with_images else "> No text or image blocks extracted.",
    ]
    if png_path:
        lines.extend(["", f"Debug rendered page image: `{png_path}`"])
    if image_rows:
        lines.extend(["", "### Images"])
        for row in image_rows:
            bbox = row["bbox"]
            lines.append(
                f"- image {row['image_number']}: `{row['file_path']}` "
                f"bbox={bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]} "
                f"size={row['width']}x{row['height']}"
            )
    return "\n".join(lines)


def build_database(
    input_pdf: str | Path,
    output_dir: str | Path,
    *,
    db_path: str | Path | None = None,
    pages: str | None = None,
    replace: bool = True,
    render_pages: bool = False,
    dpi: int = 160,
    flag_images_for_ocr: bool = True,
) -> dict[str, Any]:
    source = Path(input_pdf).resolve()
    if not source.exists():
        raise FileNotFoundError(f"Input PDF not found: {source}")

    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    asset_root = output / f"{slugify(source.stem)}_assets"
    page_dir = asset_root / "pages"
    image_dir = asset_root / "images"
    json_dir = asset_root / "visual_json"
    for directory in [image_dir, json_dir]:
        directory.mkdir(parents=True, exist_ok=True)
    if render_pages:
        page_dir.mkdir(parents=True, exist_ok=True)

    database = Path(db_path).resolve() if db_path else output / f"{slugify(source.stem)}_rag.sqlite"
    doc = fitz.open(str(source))
    source_page_count = doc.page_count
    page_indexes = parse_pages(pages, doc.page_count)

    conn = connect(database)
    ensure_schema(conn)
    if replace:
        reset_document(conn, source)

    conn.execute(
        "INSERT INTO documents(source_path, title, page_count) VALUES (?, ?, ?)",
        (str(source), doc.metadata.get("title") or source.stem, doc.page_count),
    )
    document_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    all_markdown = [
        f"# PDF Inline Image RAG Export - {source.name}",
        "",
        f"- Source: `{source}`",
        f"- Database: `{database}`",
        f"- Pages indexed: {len(page_indexes)} of {doc.page_count}",
        f"- Whole-page rendering: {'enabled for debug' if render_pages else 'disabled'}",
        "",
    ]

    image_count = 0
    for page_index in page_indexes:
        page = doc[page_index]
        page_number = page_index + 1
        rect = page.rect
        text, text_with_images, items, image_rows = extract_page_items(page, page_number, image_dir, output)
        image_count += len(image_rows)
        needs_ocr = 1 if image_rows and flag_images_for_ocr else 0

        png_path: Path | None = None
        if render_pages:
            png_path = page_dir / f"page_{page_number:04d}.png"
            render_page_png(page, png_path, dpi)

        visual_json_path = json_dir / f"page_{page_number:04d}.visual.json"
        visual_json = {
            "source": str(source),
            "page_number": page_number,
            "width": rect.width,
            "height": rect.height,
            "items": [
                {
                    "kind": item.kind,
                    "block_number": item.block_number,
                    "bbox": item.bbox,
                    "text": item.text if item.kind == "image" else item.text[:300],
                    "image_path": item.image_path,
                    "image_width": item.image_width,
                    "image_height": item.image_height,
                }
                for item in items
            ],
            "image_count": len(image_rows),
            "needs_ocr_or_vision_caption": bool(needs_ocr),
        }
        visual_json_path.write_text(json.dumps(visual_json, indent=2, ensure_ascii=False), encoding="utf-8")

        markdown = write_page_markdown(
            source.name,
            page_number,
            text,
            text_with_images,
            relative_to_output(png_path, output) if png_path else None,
            image_rows,
        )
        conn.execute(
            """
            INSERT INTO pages(
                document_id, page_number, width, height, text, text_with_images,
                markdown, png_path, visual_json_path, text_char_count, image_count, needs_ocr
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document_id,
                page_number,
                rect.width,
                rect.height,
                text,
                text_with_images,
                markdown,
                relative_to_output(png_path, output) if png_path else None,
                relative_to_output(visual_json_path, output),
                len(text),
                len(image_rows),
                needs_ocr,
            ),
        )
        page_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        for row in image_rows:
            bbox = row["bbox"]
            conn.execute(
                """
                INSERT INTO images(page_id, image_number, xref, width, height, colorspace,
                    bits_per_component, file_ext, file_path, bbox_x0, bbox_y0, bbox_x1,
                    bbox_y1, block_number, placeholder)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    page_id,
                    row["image_number"],
                    row["xref"],
                    row["width"],
                    row["height"],
                    row["colorspace"],
                    row["bpc"],
                    row["ext"],
                    row["file_path"],
                    bbox[0],
                    bbox[1],
                    bbox[2],
                    bbox[3],
                    row["block_number"],
                    row["placeholder"],
                ),
            )

        conn.execute(
            "INSERT INTO pages_fts(page_id, source_path, page_number, body) VALUES (?, ?, ?, ?)",
            (page_id, str(source), page_number, "\n\n".join([text, text_with_images, markdown])),
        )
        all_markdown.extend([markdown, ""])

    conn.commit()
    conn.close()
    doc.close()

    markdown_path = output / f"{slugify(source.stem)}_rag_export.md"
    markdown_path.write_text("\n".join(all_markdown).strip() + "\n", encoding="utf-8")
    return {
        "database": str(database),
        "assets": str(asset_root),
        "markdown": str(markdown_path),
        "pages_indexed": len(page_indexes),
        "source_page_count": source_page_count,
        "images_extracted": image_count,
    }


def search_database(db_path: str | Path, query: str, limit: int = 10) -> list[dict[str, Any]]:
    conn = connect(db_path)
    rows = conn.execute(
        """
        SELECT p.id AS page_id, p.page_number,
               snippet(pages_fts, 3, '[', ']', ' ... ', 18) AS snippet,
               p.visual_json_path, p.needs_ocr, p.image_count
        FROM pages_fts
        JOIN pages p ON p.id = pages_fts.page_id
        WHERE pages_fts MATCH ?
        ORDER BY bm25(pages_fts)
        LIMIT ?
        """,
        (query, limit),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_page(db_path: str | Path, page_number: int) -> dict[str, Any] | None:
    conn = connect(db_path)
    page = conn.execute("SELECT * FROM pages WHERE page_number = ?", (page_number,)).fetchone()
    if not page:
        conn.close()
        return None
    images = conn.execute("SELECT * FROM images WHERE page_id = ? ORDER BY image_number", (page["id"],)).fetchall()
    conn.close()
    result = dict(page)
    result["images"] = [dict(row) for row in images]
    return result


def get_image(db_path: str | Path, image_id: int | None = None, page_number: int | None = None, image_number: int | None = None) -> dict[str, Any] | None:
    conn = connect(db_path)
    if image_id is not None:
        row = conn.execute("SELECT * FROM images WHERE id = ?", (image_id,)).fetchone()
    elif page_number is not None and image_number is not None:
        row = conn.execute(
            """
            SELECT i.* FROM images i
            JOIN pages p ON p.id = i.page_id
            WHERE p.page_number = ? AND i.image_number = ?
            """,
            (page_number, image_number),
        ).fetchone()
    else:
        raise ValueError("Provide image_id or page_number plus image_number")
    conn.close()
    return dict(row) if row else None


def list_images_needing_caption(db_path: str | Path, limit: int = 50) -> list[dict[str, Any]]:
    conn = connect(db_path)
    rows = conn.execute(
        """
        SELECT i.*, p.page_number
        FROM images i
        JOIN pages p ON p.id = i.page_id
        WHERE i.caption IS NULL OR i.caption = ''
        ORDER BY p.page_number, i.image_number
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def save_image_caption(db_path: str | Path, image_id: int, caption: str, model: str | None = None) -> dict[str, Any]:
    conn = connect(db_path)
    row = conn.execute("SELECT page_id, placeholder FROM images WHERE id = ?", (image_id,)).fetchone()
    if not row:
        conn.close()
        raise ValueError(f"Image id not found: {image_id}")

    conn.execute(
        """
        UPDATE images
        SET caption = ?, caption_model = ?, caption_created_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (caption, model, image_id),
    )
    caption_text = f"{row['placeholder']}\nCaption: {caption}"
    conn.execute(
        """
        UPDATE pages
        SET text_with_images = replace(text_with_images, ?, ?),
            markdown = replace(markdown, ?, ?)
        WHERE id = ?
        """,
        (row["placeholder"], caption_text, row["placeholder"], caption_text, row["page_id"]),
    )
    page = conn.execute("SELECT * FROM pages WHERE id = ?", (row["page_id"],)).fetchone()
    conn.execute("DELETE FROM pages_fts WHERE page_id = ?", (row["page_id"],))
    conn.execute(
        "INSERT INTO pages_fts(page_id, source_path, page_number, body) VALUES (?, ?, ?, ?)",
        (page["id"], "", page["page_number"], "\n\n".join([page["text"], page["text_with_images"], page["markdown"]])),
    )
    conn.commit()
    conn.close()
    return {"image_id": image_id, "caption_saved": True}


def inspect_database(db_path: str | Path, limit: int = 50) -> dict[str, Any]:
    conn = connect(db_path)
    summary = dict(
        conn.execute(
            """
            SELECT COUNT(*) AS pages,
                   COALESCE(SUM(needs_ocr), 0) AS needs_ocr,
                   COALESCE(SUM(image_count), 0) AS images,
                   COALESCE(SUM(text_char_count), 0) AS text_chars
            FROM pages
            """
        ).fetchone()
    )
    rows = conn.execute(
        """
        SELECT page_number, text_char_count, image_count, png_path
        FROM pages
        WHERE needs_ocr = 1
        ORDER BY page_number
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()
    summary["pages_needing_ocr"] = [dict(row) for row in rows]
    return summary
