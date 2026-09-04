# packages/importers

## 負責什麼

把各種外部匯入來源（上傳檔案、行事曆等）轉成 Plan Engine 唯一認識的統一格式 `Document`：
有明確時間的資料進 `events`（`DocEvent`），其餘文字進 `text_chunks`（`TextChunk`）。
本 package 提供格式偵測（`detect_format`）、parser 選擇（`ParserRegistry`）與多份文件合併（`Document.merge`）。

## 對外 port 有哪些

- `SourcePort`：`fetch() -> RawBlob`，取得原始位元組。實作：`InMemorySource(blob)`。
- `ParserPort`：`supports(fmt) -> bool` / `parse(blob) -> Document`，把 `RawBlob` 解析成 `Document`。
- 共用型別：`RawBlob`、`Document`、`DocEvent`、`TextChunk`、`UnsupportedFormat`。
- 工具：`detect_format(filename, content_type)`（回 `csv|xlsx|md|html|pdf|docx|ics`，副檔名優先、content_type 為輔，判不出來 raise `UnsupportedFormat`）、`ParserRegistry(parsers)`、`default_registry()`。

## 不負責什麼

- 不負責取得檔案的傳輸細節（HTTP 上傳、OAuth、Google Calendar API 呼叫）——那是 service 的 adapter。
- 不儲存檔案或解析結果（見 `packages/storage`、`packages/repo`）。
- 不做語意理解、摘要或排程判斷（那是 Plan Engine 與 `packages/llm`）。
- 不決定匯入流程的非同步排程（見 `packages/queue`）。
