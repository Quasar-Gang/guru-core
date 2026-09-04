# packages/queue

## 負責什麼

- 定義所有跨 service 的**佇列 payload**（`jobs.py`），一律 Pydantic v2、frozen、`extra="forbid"`，名稱帶版本後綴（`PlanGenerateJobV1`）。
- 每個 payload 以 classmethod `queue_name()` 宣告自己所屬的佇列；`JOB_REGISTRY` 是 `queue name -> payload class` 的反查表，供 worker 還原 payload 使用。
- 提供 `QueuePort` 的兩個實作：`ArqQueue`（ARQ on Redis，正式）與 `InMemoryQueue`（測試用，可 `drain()` 同步執行）。
- 提供 `run_worker(redis_url, handlers)`：啟動 ARQ worker，把佇列上的原始 dict 依 `JOB_REGISTRY` 還原成 Pydantic model 後交給 handler。

目前的五個佇列：`import.parse`、`plan.generate`、`plan.continue`、`plan.revise`、`export.push`。

## 對外 port 有哪些

- `QueuePort`（Protocol）
  - `async enqueue(payload: JobPayload) -> JobHandle`
  - `async status(job_id: str) -> JobStatus | None`
- 附屬型別：`JobPayload`、`JobHandle`、`JobStatus`、`JOB_REGISTRY` 及五個 `*JobV1` payload。
- 實作：`ArqQueue(redis_url)`（另有 `close()`）、`InMemoryQueue()`（另有 `enqueued` 與 `drain(handlers)`）。
- Runtime helper：`run_worker(redis_url, handlers)`。

## 不負責什麼

- **不含任何業務邏輯**：job handler 由各 service 的 application 層提供並注入，這裡只負責投遞與還原。
- **不是任務狀態的權威來源**：權威狀態在 PostgreSQL；`status()` 只是佇列側的即時觀察值，Redis 清空不得造成資料遺失。
- 不做排程（cron）、不做重試策略設定、不做 dead-letter 管理。
- 不碰 DB、不碰 HTTP、不決定 worker 進程如何啟動（那是 `cmd/` 的事）。
- `arq` / `redis` 只出現在 `arq_queue.py` 與 `worker.py`；port 與 payload 完全看不到供應商型別。
