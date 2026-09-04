# packages/importers

## What it owns

Turning external import sources (uploaded files, calendars, and so on) into `Document`, the only
format the Plan Engine understands: anything with an explicit time goes into `events` (`DocEvent`),
everything else into `text_chunks` (`TextChunk`).
This package provides format detection (`detect_format`), parser selection (`ParserRegistry`) and
merging of multiple documents (`Document.merge`).

## The ports it exposes

- `SourcePort`: `fetch() -> RawBlob`, which retrieves the raw bytes. Implementation: `InMemorySource(blob)`.
- `ParserPort`: `supports(fmt) -> bool` / `parse(blob) -> Document`, which turns a `RawBlob` into a `Document`.
- Shared types: `RawBlob`, `Document`, `DocEvent`, `TextChunk`, `UnsupportedFormat`.
- Helpers: `detect_format(filename, content_type)` (returns `csv|xlsx|md|html|pdf|docx|ics`; the
  file extension wins, the content type is the fallback, and `UnsupportedFormat` is raised when
  neither identifies a format), `ParserRegistry(parsers)`, `default_registry()`.

## What it does not do

- It does not handle the transport that produces a file (HTTP uploads, OAuth, Google Calendar API
  calls) — those are service adapters.
- It does not store files or parse results (see `packages/storage` and `packages/repo`).
- It does not do semantic understanding, summarization or scheduling decisions (that is the Plan
  Engine and `packages/llm`).
- It does not decide how imports are scheduled asynchronously (see `packages/queue`).
