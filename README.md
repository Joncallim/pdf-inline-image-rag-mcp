# PDF Inline Image RAG MCP

An MCP server and CLI for building local, searchable SQLite databases from PDFs where important content appears inside inline images, figures, diagrams, or scanned image blocks.

The key rule is simple:

- Extract PDF text normally.
- Extract only actual PDF image blocks, not whole-page screenshots.
- Insert image placeholders into the page text stream at their page-flow location.
- Store every extracted image with its exact PDF bounding box.

Example `text_with_images` marker:

```text
[[IMAGE page=72 index=1 bbox=80.6,76.0,535.7,645.7 size=1896x2373 file=mtp-2_assets/images/page_0072_image_01.png]]
```

This gives an AI agent enough context to search normal text, notice where an image appeared, fetch the image asset, caption/OCR it, and save the caption back into the searchable index.

## Install

```bash
pip install git+https://github.com/Joncallim/pdf-inline-image-rag-mcp.git
```

For local development:

```bash
git clone https://github.com/Joncallim/pdf-inline-image-rag-mcp.git
cd pdf-inline-image-rag-mcp
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

## MCP Usage

Add this server to your MCP client:

```json
{
  "mcpServers": {
    "pdf-inline-image-rag": {
      "command": "pdf-inline-image-rag-mcp"
    }
  }
}
```

Available tools:

- `build_pdf_rag`
- `search_pdf_rag`
- `get_pdf_page`
- `get_pdf_image`
- `list_uncaptioned_pdf_images`
- `save_pdf_image_caption`
- `inspect_pdf_rag`

Typical flow:

1. Call `build_pdf_rag` with a PDF path and output directory.
2. Call `search_pdf_rag` for normal text queries.
3. When a result includes `[[IMAGE ...]]`, call `get_pdf_page` or `get_pdf_image`.
4. Caption or OCR the image with your preferred model.
5. Call `save_pdf_image_caption` so the caption is added to page text and FTS.

## CLI Usage

Build a database:

```bash
pdf-inline-image-rag build \
  --input /path/to/file.pdf \
  --output-dir outputs/pdf_rag \
  --replace
```

Build only selected pages:

```bash
pdf-inline-image-rag build \
  --input /path/to/file.pdf \
  --output-dir outputs/pdf_rag \
  --pages 1-10,42
```

Search:

```bash
pdf-inline-image-rag search \
  --db outputs/pdf_rag/file_rag.sqlite \
  "sector method"
```

Inspect:

```bash
pdf-inline-image-rag inspect \
  --db outputs/pdf_rag/file_rag.sqlite
```

## Output Layout

```text
outputs/pdf_rag/
  file_rag.sqlite
  file_rag_export.md
  file_assets/
    images/page_0001_image_01.png
    visual_json/page_0001.visual.json
```

Whole-page PNG rendering is disabled by default. Use `--render-pages` only for debugging.

## SQLite Tables

`pages`:

- `text`: normal embedded PDF text
- `text_with_images`: text plus inline image placeholders
- `markdown`: page-level retrieval document
- `image_count`
- `needs_ocr`

`images`:

- `file_path`
- `bbox_x0`, `bbox_y0`, `bbox_x1`, `bbox_y1`
- `width`, `height`
- `block_number`
- `placeholder`
- `caption`
- `caption_model`

`pages_fts`:

- FTS5 index over text, image placeholders, markdown, and saved captions.

## Notes

This project does not invent image captions. It extracts image blocks and makes them discoverable. Use an OCR or vision model to caption the extracted images, then persist the caption with `save_pdf_image_caption`.
