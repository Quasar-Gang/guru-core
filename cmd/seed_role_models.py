"""Load the six shipped Role Models from `seeds/`. No business logic here."""

import asyncio

from services.catalog.container import build_container

if __name__ == "__main__":
    written = asyncio.run(build_container().seed_catalog())
    print(f"upserted {len(written)} role models")
