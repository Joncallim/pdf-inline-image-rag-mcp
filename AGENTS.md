# PDF Inline Image RAG MCP Agent Guide

This Python package provides an MCP server and CLI that builds local SQLite full-text indexes from PDF text and actual inline image blocks while retaining exact page-flow placeholders and bounding boxes.

## Invariants

- Extract actual PDF image blocks, not whole-page screenshots by default. Preserve page number, image index, dimensions, file path, and exact PDF bounding box in the stored record and text placeholder.
- Keep extraction factual: the package does not invent OCR or captions. Save externally produced captions only through the existing caption path so full-text search stays synchronized.
- Keep CLI and MCP behavior aligned for their shared operations: build, search,
  page retrieval, and database inspection. Direct image retrieval, uncaptioned-
  image listing, and caption persistence are MCP-only operations; do not expand
  the CLI to match them unless the user explicitly requests that product change.
- Treat PDFs, extracted images, SQLite databases, captions, and output paths as potentially sensitive user data. Do not commit them, log their contents unnecessarily, or expose files outside the requested output/database scope.
- Validate paths and replacement behavior before filesystem writes. Do not weaken explicit `--replace` semantics or allow a request to escape the intended output/database roots.

## Repository Map

- `src/pdf_inline_image_rag_mcp/extractor.py`: PDF extraction, image placement, SQLite schema/indexing, and retrieval behavior.
- `src/pdf_inline_image_rag_mcp/server.py`: MCP tools and input/output contracts.
- `src/pdf_inline_image_rag_mcp/cli.py`: command-line surface.
- `tests/test_extractor.py`: focused extraction and persistence coverage.
- `pyproject.toml`: Python, dependency, entry-point, and pytest configuration.

## Focused Workflow

- Keep one writer per implementation or test file. For substantive work, separate core extraction/database changes from a read-only MCP/CLI contract review.
- Add a focused regression test for changes to coordinates, placeholder ordering, page selection, FTS updates, replacement, or path handling.
- Filesystem scope, replacement/deletion, untrusted PDFs, SQL/FTS construction, MCP exposure, or sensitive output changes require an independent security review.

## Validation

- Install development dependencies with `pip install -e ".[dev]"` in a virtual environment.
- Run the repository suite with `pytest`.
- When CLI or MCP contracts change, exercise the narrowest affected command/tool with a small non-sensitive fixture and inspect the generated database/export rather than relying only on unit assertions.

Report platform/library limitations and any behavior not exercised against a real PDF. Do not add large or private binary fixtures when a minimal generated or public-safe fixture will prove the contract.
