from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.web import page

from .service import demo, import_csv, import_rows

router = APIRouter()
ROWS = [{"key":"MU5101|20261116","status":"采纳","value":"PVG"},{"key":"UA857|20261116","status":"冲突","value":"SFO"},{"key":"CA981|20261117","status":"隔离","value":"JFK"}]


@router.get("/legs", response_class=HTMLResponse)
def view(request: Request):
    return page(request, "m1.html", "航段采信", "/api/legs/import", ROWS)


@router.post("/api/legs/import")
async def execute(request: Request):
    """Import real legs.

    ``text/csv`` (or any non-JSON body) is parsed as CSV so physical line
    numbers and a truncated tail are preserved; a JSON body accepts
    ``{"rows": [...]}`` or ``{"csv": "..."}``.  An empty body keeps the sample
    flow used by the page button.
    """
    raw = await request.body()
    if not raw:
        return demo()
    content_type = request.headers.get("content-type", "")
    text = raw.decode("utf-8")
    if "application/json" in content_type:
        payload = await request.json()
        if isinstance(payload, list):
            return import_rows(payload)
        if not isinstance(payload, dict):
            from app.errors import DomainError

            raise DomainError("BAD_PAYLOAD", "JSON 主体必须是对象或数组", status=422)
        if "csv" in payload:
            return import_csv(payload["csv"])
        if "rows" in payload:
            return import_rows(payload["rows"])
        if not payload:
            return demo()
        from app.errors import DomainError

        raise DomainError("BAD_PAYLOAD", "需要 csv 或 rows 字段", status=422)
    return import_csv(text)
