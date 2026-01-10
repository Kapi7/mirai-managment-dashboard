"""
Emma Service - AI Sales & Support Agent
Runs as a standalone service that:
1. Polls Gmail for customer emails
2. Pushes to Mirai Dashboard for classification and AI draft
3. Provides API for testing Emma responses
"""
import os
import asyncio
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

# Gmail poller
from gmail_poller import (
    start_gmail_poller, stop_gmail_poller,
    get_gmail_poller_status, force_cycle, reset_cursor
)

# Emma agent
from emma_agent import respond_as_emma, detect_emotional_state

app = FastAPI(title="Emma Service", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== MODELS ====================

class ChatRequest(BaseModel):
    message: str
    customer_email: Optional[str] = None
    customer_name: Optional[str] = None
    cart_items: Optional[List[str]] = []
    geo: Optional[str] = None
    history: Optional[List[Dict[str, Any]]] = []


class ChatResponse(BaseModel):
    response: str
    emotional_state: Dict[str, Any]


# ==================== HEALTH ====================

@app.get("/healthz")
async def health():
    return {"status": "ok", "service": "emma"}


@app.get("/status")
async def status():
    poller = get_gmail_poller_status()
    return {
        "service": "emma",
        "gmail_poller": poller,
        "dashboard_url": os.getenv("MIRAI_DASHBOARD_URL", "not set"),
        "database_configured": bool(os.getenv("MIRAI_DATABASE_URL"))
    }


# ==================== GMAIL POLLER ====================

@app.post("/poller/start")
async def poller_start():
    try:
        ok = start_gmail_poller()
        return {"started": ok, **get_gmail_poller_status()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/poller/stop")
async def poller_stop():
    stop_gmail_poller()
    return {"stopped": True, **get_gmail_poller_status()}


@app.post("/poller/force")
async def poller_force():
    """Force an immediate poll cycle"""
    force_cycle()
    return {"forced": True, **get_gmail_poller_status()}


@app.post("/poller/reset")
async def poller_reset():
    """Reset seen emails cursor"""
    reset_cursor()
    return {"reset": True, **get_gmail_poller_status()}


@app.get("/poller/status")
async def poller_status():
    return get_gmail_poller_status()


# ==================== EMMA CHAT ====================

@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """
    Send a message to Emma and get a response.
    Used for testing or direct API integration.
    """
    try:
        # Detect emotional state
        emotion = detect_emotional_state(req.message)

        # Get Emma's response
        first_name = ""
        if req.customer_name:
            first_name = req.customer_name.split()[0]

        response = respond_as_emma(
            first_name=first_name,
            cart_items=req.cart_items or [],
            customer_msg=req.message,
            history=req.history or [],
            first_contact=False,
            geo=req.geo,
            customer_email=req.customer_email
        )

        return ChatResponse(
            response=response,
            emotional_state=emotion
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/analyze-emotion")
async def analyze_emotion(message: str):
    """Analyze the emotional state of a message"""
    return detect_emotional_state(message)


# ==================== STARTUP ====================

@app.on_event("startup")
async def startup():
    """Start Gmail poller on service startup"""
    if os.getenv("GMAIL_POLLER_AUTOSTART", "1") == "1":
        try:
            started = start_gmail_poller()
            print(f"[emma-service] Gmail poller autostart: {'ok' if started else 'skipped (missing credentials)'}")
        except Exception as e:
            print(f"[emma-service] Gmail poller autostart failed: {e}")
    else:
        print("[emma-service] Gmail poller autostart disabled")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "5002"))
    uvicorn.run(app, host="0.0.0.0", port=port)
