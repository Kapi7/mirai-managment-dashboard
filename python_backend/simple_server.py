"""
Simple FastAPI server for dashboard reports - NO automation, NO Telegram, NO complexity
Just: fetch data from APIs → calculate metrics → return JSON
"""
import os
from datetime import datetime, date, timedelta
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import pytz

app = FastAPI(title="Mirai Reports API - Simple", version="2.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class DateRangeRequest(BaseModel):
    start_date: str  # YYYY-MM-DD
    end_date: str    # YYYY-MM-DD


@app.get("/health")
async def health():
    return {"status": "ok", "message": "Simple FastAPI is running"}


@app.post("/daily-report")
async def daily_report(req: DateRangeRequest):
    """
    Return daily metrics for the date range.
    This is a simplified version that will call the actual data fetching functions.
    """
    try:
        # Parse dates
        start_date = datetime.strptime(req.start_date, "%Y-%m-%d").date()
        end_date = datetime.strptime(req.end_date, "%Y-%m-%d").date()

        if start_date > end_date:
            raise HTTPException(status_code=400, detail="start_date must be <= end_date")

        # Import the actual data fetching logic
        # We'll use the existing modules but call them cleanly
        from report_logic import fetch_daily_reports

        data = fetch_daily_reports(start_date, end_date)

        return {"data": data}

    except ImportError as e:
        # If report_logic doesn't exist yet, return mock data
        return {
            "data": [
                {
                    "date": req.start_date,
                    "label": "Mock Data",
                    "orders": 10,
                    "gross": 1000.0,
                    "discounts": 50.0,
                    "refunds": 0.0,
                    "net": 950.0,
                    "cogs": 300.0,
                    "shipping_charged": 100.0,
                    "shipping_cost": 50.0,
                    "google_spend": 100.0,
                    "meta_spend": 50.0,
                    "total_spend": 150.0,
                    "google_pur": 5,
                    "meta_pur": 3,
                    "google_cpa": 20.0,
                    "meta_cpa": 16.67,
                    "general_cpa": 18.75,
                    "psp_usd": 25.0,
                    "operational_profit": 425.0,
                    "net_margin": 425.0,
                    "margin_pct": 44.74,
                    "aov": 95.0,
                    "returning_customers": 2
                }
            ]
        }
    except Exception as e:
        return {"error": str(e), "data": []}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run("simple_server:app", host="0.0.0.0", port=port, reload=False)
