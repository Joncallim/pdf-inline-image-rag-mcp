from __future__ import annotations

import sqlite3
from pathlib import Path

import fitz

from pdf_inline_image_rag_mcp.extractor import build_database, get_page, save_image_caption, search_database


def make_sample_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=300, height=300)
    page.insert_text((40, 40), "Before image", fontsize=12)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 24, 24), False)
    pix.clear_with(0x00AAFF)
    page.insert_image(fitz.Rect(50, 70, 150, 170), pixmap=pix)
    page.insert_text((40, 210), "After image", fontsize=12)
    doc.save(path)
    doc.close()


def test_build_database_preserves_inline_image_location(tmp_path: Path) -> None:
    pdf_path = tmp_path / "sample.pdf"
    make_sample_pdf(pdf_path)

    result = build_database(pdf_path, tmp_path / "out")
    db_path = result["database"]

    page = get_page(db_path, 1)
    assert page is not None
    assert "Before image" in page["text"]
    assert "After image" in page["text"]
    assert "[[IMAGE page=1 index=1" in page["text_with_images"]
    assert page["text_with_images"].index("Before image") < page["text_with_images"].index("[[IMAGE")
    assert page["text_with_images"].index("[[IMAGE") < page["text_with_images"].index("After image")
    assert page["image_count"] == 1
    assert page["images"][0]["bbox_x0"] == 50.0
    assert Path(tmp_path / "out" / page["images"][0]["file_path"]).exists()


def test_search_and_caption_update_fts(tmp_path: Path) -> None:
    pdf_path = tmp_path / "sample.pdf"
    make_sample_pdf(pdf_path)
    result = build_database(pdf_path, tmp_path / "out")
    db_path = result["database"]

    rows = search_database(db_path, "Before", 5)
    assert rows and rows[0]["page_number"] == 1

    page = get_page(db_path, 1)
    image_id = page["images"][0]["id"]
    save_image_caption(db_path, image_id, "blue square diagram", "test")
    rows = search_database(db_path, "blue square", 5)
    assert rows and rows[0]["page_number"] == 1
