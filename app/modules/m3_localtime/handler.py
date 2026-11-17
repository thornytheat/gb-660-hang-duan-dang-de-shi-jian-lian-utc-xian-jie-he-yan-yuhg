from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from app.web import page
from .service import demo

router = APIRouter()
ROWS = [{"key":"JFK|01:30","status":"重叠","value":"fold 1"},{"key":"JFK|02:30","status":"跳时","value":"—"},{"key":"PVG|09:00","status":"唯一","value":"+08:00"}]

@router.get("/local-time", response_class=HTMLResponse)
def view(request: Request):
    return page(request, "m3.html", "当地时刻", "/api/local-time/resolve", ROWS)

@router.post("/api/local-time/resolve")
def execute():
    return demo()

