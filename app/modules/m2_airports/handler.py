from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from app.web import page
from .service import demo

router = APIRouter()
ROWS = [{"key":"PVG","status":"Asia/Shanghai","value":"+08:00"},{"key":"JFK","status":"America/New_York","value":"DST"},{"key":"LHR","status":"Europe/London","value":"DST"}]

@router.get("/airports", response_class=HTMLResponse)
def view(request: Request):
    return page(request, "m2.html", "机场时区", "/api/airports", ROWS)

@router.post("/api/airports")
def execute():
    return demo()

