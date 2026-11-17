from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from app.web import page
from .service import demo

router = APIRouter()
ROWS = [{"key":"PVG-JFK","status":"有效","value":"14:20"},{"key":"JFK-LHR","status":"有效","value":"06:45"},{"key":"LHR-PVG","status":"冲突","value":"-00:20"}]

@router.get("/itineraries", response_class=HTMLResponse)
def view(request: Request):
    return page(request, "m4.html", "UTC 航链", "/api/itineraries/build", ROWS)

@router.post("/api/itineraries/build")
def execute():
    return demo()

