"""Load the six shipped Role Models from `seeds/`. No business logic here."""

import asyncio

from packages.config import load_dotenv
from services.catalog.container import build_container

if __name__ == "__main__":
    load_dotenv()
    written = asyncio.run(build_container().seed_catalog())
    print(f"upserted {len(written)} role models")
