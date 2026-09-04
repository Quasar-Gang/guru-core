# packages/storage

## What it owns

The object storage abstraction and its implementations: write, read and delete bytes by key, report
whether a key exists, and mint time-limited presigned URLs so the frontend can upload and download
directly without going through the application.

Three implementations ship today:

- `LocalFileStorage`: the MVP production implementation. Objects are written under `root` on the
  local filesystem and `content_type` is kept in a sibling `.meta` JSON sidecar. Presigning yields
  `{public_base_url}/{key}?exp=…&op=…&sig=…`, where the signature is the hex digest of
  `HMAC-SHA256(signing_secret, "{op}:{key}:{exp}")` and can be checked with
  `LocalFileStorage.verify_signature(...)`. Absolute keys and keys containing `..` are always
  rejected; parent directories are created on demand.
- `InMemoryStorage`: for tests and local development. Data lives in process memory and presigning
  returns `memory://{op}/{key}?exp=…`.
- `R2Storage`: Cloudflare R2 over its S3-compatible API. It talks to
  `https://{account_id}.r2.cloudflarestorage.com` with SigV4 and `region_name="auto"`, presigns with
  `generate_presigned_url`, and runs every (synchronous) boto3 call in `asyncio.to_thread` so the
  port stays genuinely async. A missing key raises `ObjectNotFound` from `get`; `delete` is a no-op
  for a key that is not there. `r2.py` is the only module allowed to import `boto3`.

### Switching to R2

Nothing in the application changes — the switch is entirely configuration. Set

```
STORAGE_BACKEND=r2
R2_ACCOUNT_ID=…
R2_ACCESS_KEY_ID=…
R2_SECRET_ACCESS_KEY=…
R2_BUCKET=…
```

and `build_container` (`services/api/container.py`) constructs `R2Storage` instead of
`LocalFileStorage`. If `STORAGE_BACKEND=r2` and any of the four variables is empty, container
construction fails fast with a `ValueError` naming the missing ones.

## The ports it exposes

The names listed in `packages.storage.__all__`:

- `StoragePort` (Protocol): `put` / `get` / `delete` / `exists` / `presign_put` / `presign_get`
- `StoredObject` (Pydantic model): `key`, `size`, `content_type`
- `ObjectNotFound` (subclass of `KeyError`): raised by `get` for a missing key
- `LocalFileStorage`, `InMemoryStorage`, `R2Storage`: the three implementations

Every other module (`ports.py`, `local.py`, `memory.py`, `r2.py`) is private — always import from
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
- It does not create or configure buckets, nor cover CDNs, lifecycle rules or virus scanning.
