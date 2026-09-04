# packages/storage

## What it owns

The object storage abstraction and its implementations: write, read and delete bytes by key, report
whether a key exists, and mint time-limited presigned URLs so the frontend can upload and download
directly without going through the application.

Two implementations ship today:

- `LocalFileStorage`: the MVP production implementation. Objects are written under `root` on the
  local filesystem and `content_type` is kept in a sibling `.meta` JSON sidecar. Presigning yields
  `{public_base_url}/{key}?exp=…&op=…&sig=…`, where the signature is the hex digest of
  `HMAC-SHA256(signing_secret, "{op}:{key}:{exp}")` and can be checked with
  `LocalFileStorage.verify_signature(...)`. Absolute keys and keys containing `..` are always
  rejected; parent directories are created on demand.
- `InMemoryStorage`: for tests and local development. Data lives in process memory and presigning
  returns `memory://{op}/{key}?exp=…`.

## The ports it exposes

The names listed in `packages.storage.__all__`:

- `StoragePort` (Protocol): `put` / `get` / `delete` / `exists` / `presign_put` / `presign_get`
- `StoredObject` (Pydantic model): `key`, `size`, `content_type`
- `ObjectNotFound` (subclass of `KeyError`): raised by `get` for a missing key
- `LocalFileStorage`, `InMemoryStorage`: the two implementations

Every other module (`ports.py`, `local.py`, `memory.py`) is private — always import from
`packages.storage`.

## What it does not do

- It does not parse or convert file contents (that is `packages/importers`).
- It does not persist or query metadata (file records live in the database, owned by
  `packages/repo`); the `.meta` sidecar is purely an implementation detail of how
  `LocalFileStorage` remembers a content type.
- It does not serve the HTTP endpoint that validates presigned URLs; `verify_signature` is only the
  predicate, while routing and authorization live in the API service.
- It does not handle authorization or tenant isolation — callers are responsible for encoding
  `user_id` into the key.
- It does not cover Cloudflare R2 (`R2Storage` is a later task), CDNs, lifecycle rules or virus
  scanning.
