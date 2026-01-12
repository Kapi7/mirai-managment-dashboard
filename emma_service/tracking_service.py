"""
Tracking Service - Proactive shipment monitoring via AfterShip

Features:
- Sync shipments from Shopify fulfillments
- Check tracking status via AfterShip API
- Detect delays and delivery events
- Enable proactive customer outreach
"""

import os
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import json


AFTERSHIP_API_KEY = os.getenv("AFTERSHIP_API_KEY")
AFTERSHIP_BASE_URL = "https://api.aftership.com/v4"

# Carrier code mapping for AfterShip
CARRIER_CODES = {
    "korea post": "korea-post",
    "korea-post": "korea-post",
    "k-packet": "korea-post",
    "ems": "ems",
    "dhl": "dhl",
    "dhl express": "dhl",
    "usps": "usps",
    "ups": "ups",
    "fedex": "fedex",
    "cj logistics": "cj-logistics",
    "cj대한통운": "cj-logistics",
}


def get_carrier_code(carrier_name: str) -> str:
    """Convert carrier name to AfterShip carrier code."""
    if not carrier_name:
        return "korea-post"  # Default for Mirai
    return CARRIER_CODES.get(carrier_name.lower().strip(), "korea-post")


def check_tracking_aftership(tracking_number: str, carrier: Optional[str] = None) -> Dict[str, Any]:
    """
    Check tracking status via AfterShip API.

    Returns:
        {
            "success": bool,
            "status": str,  # pending, in_transit, out_for_delivery, delivered, exception, expired
            "status_detail": str,
            "checkpoints": list,
            "last_checkpoint": str,
            "last_checkpoint_time": datetime,
            "estimated_delivery": datetime,
            "delivered_at": datetime,
            "error": str  # if failed
        }
    """
    if not AFTERSHIP_API_KEY:
        return {
            "success": False,
            "error": "AFTERSHIP_API_KEY not configured",
            "status": "unknown"
        }

    carrier_code = get_carrier_code(carrier) if carrier else None

    headers = {
        "aftership-api-key": AFTERSHIP_API_KEY,
        "Content-Type": "application/json"
    }

    # First, try to get existing tracking
    try:
        # Try to get tracking by number
        url = f"{AFTERSHIP_BASE_URL}/trackings/{carrier_code}/{tracking_number}" if carrier_code else f"{AFTERSHIP_BASE_URL}/trackings/{tracking_number}"
        response = requests.get(url, headers=headers, timeout=30)

        if response.status_code == 404:
            # Tracking not found, create it
            create_url = f"{AFTERSHIP_BASE_URL}/trackings"
            payload = {
                "tracking": {
                    "tracking_number": tracking_number,
                }
            }
            if carrier_code:
                payload["tracking"]["slug"] = carrier_code

            create_response = requests.post(create_url, headers=headers, json=payload, timeout=30)

            if create_response.status_code in [200, 201]:
                # Wait a moment and fetch again
                response = requests.get(url, headers=headers, timeout=30)
            else:
                return {
                    "success": False,
                    "error": f"Failed to create tracking: {create_response.text}",
                    "status": "unknown"
                }

        if response.status_code == 200:
            data = response.json()
            tracking = data.get("data", {}).get("tracking", {})

            # Parse checkpoints
            checkpoints = tracking.get("checkpoints", [])
            last_checkpoint = checkpoints[-1] if checkpoints else {}

            # Determine status
            tag = tracking.get("tag", "Pending").lower()
            status_map = {
                "pending": "pending",
                "infotransit": "in_transit",
                "intransit": "in_transit",
                "outfordelivery": "out_for_delivery",
                "delivered": "delivered",
                "exception": "exception",
                "expired": "expired",
                "attemptfail": "exception",
            }
            status = status_map.get(tag.replace(" ", "").replace("_", ""), "in_transit")

            # Parse dates
            delivered_at = None
            if status == "delivered" and last_checkpoint:
                delivered_at = last_checkpoint.get("checkpoint_time")

            estimated_delivery = tracking.get("expected_delivery")

            return {
                "success": True,
                "status": status,
                "status_detail": tracking.get("subtag_message", ""),
                "tag": tracking.get("tag"),
                "checkpoints": checkpoints,
                "last_checkpoint": last_checkpoint.get("message", "") if last_checkpoint else "",
                "last_checkpoint_time": last_checkpoint.get("checkpoint_time") if last_checkpoint else None,
                "estimated_delivery": estimated_delivery,
                "delivered_at": delivered_at,
                "carrier": tracking.get("slug"),
                "origin": tracking.get("origin_country_iso3"),
                "destination": tracking.get("destination_country_iso3"),
                "signed_by": tracking.get("signed_by"),
            }
        else:
            return {
                "success": False,
                "error": f"AfterShip API error: {response.status_code} - {response.text}",
                "status": "unknown"
            }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "status": "unknown"
        }


def get_tracking_url(tracking_number: str, carrier: str = None) -> str:
    """Generate tracking URL for the customer."""
    carrier_code = get_carrier_code(carrier) if carrier else "korea-post"

    urls = {
        "korea-post": f"https://service.epost.go.kr/trace.RetrieveEmsRi498TraceList.comm?POST_CODE={tracking_number}",
        "usps": f"https://tools.usps.com/go/TrackConfirmAction?tLabels={tracking_number}",
        "dhl": f"https://www.dhl.com/en/express/tracking.html?AWB={tracking_number}",
        "ups": f"https://www.ups.com/track?tracknum={tracking_number}",
        "fedex": f"https://www.fedex.com/fedextrack/?trknbr={tracking_number}",
        "ems": f"https://www.ems.post/en/global-network/tracking?q={tracking_number}",
    }

    return urls.get(carrier_code, f"https://track.aftership.com/{tracking_number}")


def sync_shipments_from_shopify(shopify_store: str, shopify_token: str, days_back: int = 30) -> List[Dict]:
    """
    Sync shipments from Shopify fulfillments.

    Returns list of shipments with tracking info.
    """
    api_version = "2024-01"
    base_url = f"https://{shopify_store}/admin/api/{api_version}"
    headers = {
        "X-Shopify-Access-Token": shopify_token,
        "Content-Type": "application/json"
    }

    # Get orders from the last N days with fulfillments
    since_date = (datetime.utcnow() - timedelta(days=days_back)).isoformat()

    shipments = []

    try:
        # Fetch orders with fulfillment status
        url = f"{base_url}/orders.json?status=any&fulfillment_status=shipped&created_at_min={since_date}&limit=250"
        response = requests.get(url, headers=headers, timeout=60)

        if response.status_code != 200:
            print(f"[tracking_service] Shopify error: {response.status_code}")
            return []

        orders = response.json().get("orders", [])

        for order in orders:
            fulfillments = order.get("fulfillments", [])

            for fulfillment in fulfillments:
                tracking_number = fulfillment.get("tracking_number")
                if not tracking_number:
                    continue

                # Get customer info
                customer = order.get("customer", {})
                shipping = order.get("shipping_address", {})

                shipment = {
                    "order_id": str(order.get("id")),
                    "order_number": order.get("name", "").replace("#", ""),
                    "customer_email": customer.get("email") or order.get("email"),
                    "customer_name": f"{customer.get('first_name', '')} {customer.get('last_name', '')}".strip() or shipping.get("name"),
                    "tracking_number": tracking_number,
                    "carrier": fulfillment.get("tracking_company", "Korea Post"),
                    "shipped_at": fulfillment.get("created_at"),
                    "delivery_address_city": shipping.get("city"),
                    "delivery_address_country": shipping.get("country"),
                    "fulfillment_status": fulfillment.get("status"),
                    "order_total": order.get("total_price"),
                    "line_items": [item.get("title") for item in order.get("line_items", [])],
                }

                shipments.append(shipment)

        return shipments

    except Exception as e:
        print(f"[tracking_service] Error syncing from Shopify: {e}")
        return []


def detect_delays(shipped_at: datetime, estimated_delivery: datetime = None, status: str = "in_transit") -> Dict[str, Any]:
    """
    Detect if a shipment is delayed based on expected delivery times.

    Mirai ships from Korea - typical times:
    - US: 10-19 business days
    - EU: 12-21 business days
    - Asia: 7-14 business days
    """
    if status == "delivered":
        return {"delayed": False, "delay_days": 0}

    if not shipped_at:
        return {"delayed": False, "delay_days": 0}

    if isinstance(shipped_at, str):
        shipped_at = datetime.fromisoformat(shipped_at.replace("Z", "+00:00")).replace(tzinfo=None)

    days_in_transit = (datetime.utcnow() - shipped_at).days

    # If we have estimated delivery and it's passed
    if estimated_delivery:
        if isinstance(estimated_delivery, str):
            estimated_delivery = datetime.fromisoformat(estimated_delivery.replace("Z", "+00:00")).replace(tzinfo=None)

        if datetime.utcnow() > estimated_delivery:
            delay_days = (datetime.utcnow() - estimated_delivery).days
            return {"delayed": True, "delay_days": delay_days, "reason": "Past estimated delivery"}

    # Default thresholds (international from Korea)
    if days_in_transit > 25:
        return {"delayed": True, "delay_days": days_in_transit - 19, "reason": "Exceeded typical delivery window"}
    elif days_in_transit > 19:
        return {"delayed": False, "delay_days": 0, "warning": "Approaching delivery window limit"}

    return {"delayed": False, "delay_days": 0}


def get_shipment_stats(shipments: List[Dict]) -> Dict[str, Any]:
    """Calculate statistics from shipment list."""
    total = len(shipments)
    if total == 0:
        return {
            "total": 0,
            "pending": 0,
            "in_transit": 0,
            "out_for_delivery": 0,
            "delivered": 0,
            "exception": 0,
            "delayed": 0,
        }

    stats = {
        "total": total,
        "pending": sum(1 for s in shipments if s.get("status") == "pending"),
        "in_transit": sum(1 for s in shipments if s.get("status") == "in_transit"),
        "out_for_delivery": sum(1 for s in shipments if s.get("status") == "out_for_delivery"),
        "delivered": sum(1 for s in shipments if s.get("status") == "delivered"),
        "exception": sum(1 for s in shipments if s.get("status") == "exception"),
        "delayed": sum(1 for s in shipments if s.get("delay_detected")),
        "followup_pending": sum(1 for s in shipments if s.get("status") == "delivered" and not s.get("delivery_followup_sent")),
    }

    return stats


if __name__ == "__main__":
    # Test tracking lookup
    import sys

    if len(sys.argv) > 1:
        tracking = sys.argv[1]
        print(f"Checking tracking: {tracking}")
        result = check_tracking_aftership(tracking)
        print(json.dumps(result, indent=2, default=str))
    else:
        print("Usage: python tracking_service.py <tracking_number>")
