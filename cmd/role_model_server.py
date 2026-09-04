"""Role Model Service HTTP 入口（port 8001）。零業務邏輯。"""

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "services.role_model.container:create_asgi_app",
        factory=True,
        host="0.0.0.0",  # noqa: S104 - 容器內對外服務
        port=8001,
    )
