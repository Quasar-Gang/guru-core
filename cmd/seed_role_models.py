"""Seed `role_models` from `seeds/role_models/*.yaml`. No business logic here."""

import asyncio

from services.role_model.container import build_container, seed_role_models

if __name__ == "__main__":
    written = asyncio.run(seed_role_models(build_container()))
    print(f"upserted {len(written)} role models")
