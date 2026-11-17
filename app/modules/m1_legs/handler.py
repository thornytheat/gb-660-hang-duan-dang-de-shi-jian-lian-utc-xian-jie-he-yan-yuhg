from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from app.web import page
from .service import demo

router = APIRouter()
ROWS = [{"key":"MU5101|20261116","status":"采纳","value":"PVG"},{"key":"UA857|20261116","status":"冲突","value":"SFO"},{"key":"CA981|20261117","status":"隔离","value":"JFK"}]

@router.get("/legs", response_class=HTMLResponse)
def view(request: Request):
    return page(request, "m1.html", "航段采信", "/api/legs/import", ROWS)

@router.post("/api/legs/import")
def execute():
    return demo()

