"""HTTP entrypoint for the Role Model service (port 8001). No business logic here."""

import uvicorn

from packages.logging import configure_logging

if __name__ == "__main__":
    configure_logging("role-model")
    uvicorn.run(
        "services.role_model.container:create_asgi_app",
        factory=True,
        host="0.0.0.0",  # noqa: S104 - listens for traffic outside the container
        port=8001,
    )
