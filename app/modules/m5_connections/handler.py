from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from app.web import page
from .service import demo

router = APIRouter()
ROWS = [{"key":"JFK T1-T4","status":"可衔接","value":"155"},{"key":"LHR T3-T5","status":"不足","value":"70"},{"key":"PVG T1-T2","status":"可衔接","value":"120"}]

@router.get("/connections", response_class=HTMLResponse)
def view(request: Request):
    return page(request, "m5.html", "衔接判定", "/api/connections/check", ROWS)

@router.post("/api/connections/check")
def execute():
    return demo()

