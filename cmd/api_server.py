"""HTTP entrypoint for the API service (port 8000). No business logic here."""

import uvicorn

from packages.config import load_dotenv
from packages.logging import configure_logging

if __name__ == "__main__":
    load_dotenv()
    configure_logging("api")
    uvicorn.run(
        "services.api.container:create_asgi_app",
        factory=True,
        host="0.0.0.0",  # noqa: S104 - listens for traffic outside the container
        port=8000,
    )
