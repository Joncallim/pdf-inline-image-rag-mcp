from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from .extractor import (
    build_database,
    get_image,
    get_page,
    inspect_database,
    list_images_needing_caption,
    save_image_caption,
    search_database,
)


mcp = FastMCP("pdf-inline-image-rag")


@mcp.tool()
def build_pdf_rag(
    pdf_path: str,
    output_dir: str,
    db_path: str | None = None,
    pages: str | None = None,
    replace: bool = True,
    flag_images_for_ocr: bool = True,
    render_pages: bool = False,
    dpi: int = 160,
) -> dict[str, Any]:
    """Build a SQLite RAG database from a PDF.

    Text is extracted normally. Only actual PDF image blocks are extracted, and
    image placeholders are inserted into text_with_images at their page location.
    """
    return build_database(
        pdf_path,
        output_dir,
        db_path=db_path,
        pages=pages,
        replace=replace,
        render_pages=render_pages,
        dpi=dpi,
        flag_images_for_ocr=flag_images_for_ocr,
    )


@mcp.tool()
def search_pdf_rag(db_path: str, query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Search the FTS index and return matching pages with snippets."""
    return search_database(db_path, query, limit)


@mcp.tool()
def get_pdf_page(db_path: str, page_number: int) -> dict[str, Any] | None:
    """Return a page record, including text_with_images and image metadata."""
    return get_page(db_path, page_number)


@mcp.tool()
def get_pdf_image(
    db_path: str,
    image_id: int | None = None,
    page_number: int | None = None,
    image_number: int | None = None,
) -> dict[str, Any] | None:
    """Return image metadata by image_id or by page_number plus image_number."""
    return get_image(db_path, image_id=image_id, page_number=page_number, image_number=image_number)


@mcp.tool()
def list_uncaptioned_pdf_images(db_path: str, limit: int = 50) -> list[dict[str, Any]]:
    """List extracted images that do not yet have captions."""
    return list_images_needing_caption(db_path, limit)


@mcp.tool()
def save_pdf_image_caption(
    db_path: str,
    image_id: int,
    caption: str,
    model: str | None = None,
) -> dict[str, Any]:
    """Save an AI or OCR caption and update page text plus FTS search content."""
    return save_image_caption(db_path, image_id, caption, model)


@mcp.tool()
def inspect_pdf_rag(db_path: str, limit: int = 50) -> dict[str, Any]:
    """Return database counts and pages flagged for OCR or vision captioning."""
    return inspect_database(db_path, limit)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
