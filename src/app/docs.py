"""Interactive docs at /docs: Swagger UI from the pinned `fastapi-swagger` package, no CDN.

Every script and style is a file served from this origin, so the page runs under a strict CSP.
"""

from html import escape
from importlib.resources import files

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.middleware import DOCS_PATH

ASSETS_PATH = f"{DOCS_PATH}/assets"


def mount(app: FastAPI) -> None:
    app.mount(
        ASSETS_PATH,
        StaticFiles(
            directory=str(files("app") / "static"),
            packages=[("fastapi_swagger", "resources")],
        ),
        name="docs-assets",
    )

    @app.get(DOCS_PATH, include_in_schema=False)
    async def swagger_ui(request: Request) -> HTMLResponse:
        root = request.scope.get("root_path", "").rstrip("/")
        assets = escape(root + ASSETS_PATH)
        return HTMLResponse(f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(app.title)}</title>
<link rel="icon" type="image/png" href="{assets}/favicon-32x32.png">
<link rel="stylesheet" href="{assets}/swagger-ui.css">
</head>
<body>
<div id="swagger-ui" data-openapi-url="{escape(root + str(app.openapi_url))}"></div>
<script src="{assets}/swagger-ui-bundle.js"></script>
<script src="{assets}/swagger-init.js"></script>
</body>
</html>
""")
