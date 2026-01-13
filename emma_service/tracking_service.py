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
AFTERSHIP_BASE_URL = "https://api.aftership.com/tracking/2024-10"

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
    "gofo": "gofo",
    "other": None,  # Let AfterShip auto-detect
}


def get_carrier_code(carrier_name: str) -> Optional[str]:
    """Convert carrier name to AfterShip carrier code."""
    if not carrier_name:
        return None  # Let AfterShip auto-detect
    carrier_lower = carrier_name.lower().strip()
    if carrier_lower in CARRIER_CODES:
        return CARRIER_CODES[carrier_lower]
    return None  # Let AfterShip auto-detect for unknown carriers


def check_tracking_aftership(tracking_number: str, carrier: Optional[str] = None, verbose: bool = False) -> Dict[str, Any]:
    """
    Check tracking status via AfterShip API (2024-10 version).

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
    log_prefix = f"[AfterShip:{tracking_number}]"

    if not AFTERSHIP_API_KEY:
        print(f"{log_prefix} ERROR: AFTERSHIP_API_KEY not configured")
        return {
            "success": False,
            "error": "AFTERSHIP_API_KEY not configured",
            "status": "unknown"
        }

    if verbose:
        print(f"{log_prefix} Starting check with carrier={carrier}")

    carrier_code = get_carrier_code(carrier) if carrier else None

    headers = {
        "as-api-key": AFTERSHIP_API_KEY,
        "Content-Type": "application/json"
    }

    try:
        # First, try to find existing tracking by searching (don't filter by slug - AfterShip may detect different carrier)
        search_url = f"{AFTERSHIP_BASE_URL}/trackings"
        params = {"tracking_numbers": tracking_number}

        if verbose:
            print(f"{log_prefix} Searching for existing tracking...")
        response = requests.get(search_url, headers=headers, params=params, timeout=30)

        tracking = None
        if response.status_code == 200:
            data = response.json()
            trackings = data.get("data", {}).get("trackings", [])
            if trackings:
                tracking = trackings[0]
                if verbose:
                    print(f"{log_prefix} Found existing tracking, tag={tracking.get('tag')}, checkpoints={len(tracking.get('checkpoints', []))}")
        else:
            print(f"{log_prefix} Search failed: status={response.status_code}, response={response.text[:200]}")

        # If not found, create new tracking
        if not tracking:
            if verbose:
                print(f"{log_prefix} Not found, creating new tracking with carrier_code={carrier_code}")
            create_url = f"{AFTERSHIP_BASE_URL}/trackings"
            payload = {
                "tracking_number": tracking_number,
            }
            if carrier_code:
                payload["slug"] = carrier_code

            create_response = requests.post(create_url, headers=headers, json=payload, timeout=30)
            print(f"{log_prefix} Create response: status={create_response.status_code}")

            if create_response.status_code in [200, 201]:
                # 2024 API returns tracking directly in data, not data.tracking
                resp_data = create_response.json().get("data", {})
                tracking = resp_data if "tracking_number" in resp_data else resp_data.get("tracking", {})
                if verbose:
                    print(f"{log_prefix} Created tracking, tag={tracking.get('tag')}")
            else:
                create_json = create_response.json()
                print(f"{log_prefix} Create failed: {create_json.get('meta', {}).get('code')}: {create_json.get('meta', {}).get('message', '')}")
                # Check if tracking already exists - fetch it instead
                if create_json.get("meta", {}).get("code") == 4003:
                    # Tracking already exists, get its ID and fetch it
                    existing_id = create_json.get("data", {}).get("id")
                    existing_slug = create_json.get("data", {}).get("slug")
                    if existing_id:
                        fetch_url = f"{AFTERSHIP_BASE_URL}/trackings/{existing_id}"
                        fetch_response = requests.get(fetch_url, headers=headers, timeout=30)
                        if fetch_response.status_code == 200:
                            resp_data = fetch_response.json().get("data", {})
                            tracking = resp_data if "tracking_number" in resp_data else resp_data.get("tracking", {})

                # Try without carrier code if it failed and tracking not found yet
                if not tracking and carrier_code:
                    payload.pop("slug", None)
                    create_response = requests.post(create_url, headers=headers, json=payload, timeout=30)
                    if create_response.status_code in [200, 201]:
                        resp_data = create_response.json().get("data", {})
                        tracking = resp_data if "tracking_number" in resp_data else resp_data.get("tracking", {})

                if not tracking:
                    return {
                        "success": False,
                        "error": f"Failed to create tracking: {create_response.text}",
                        "status": "unknown"
                    }

        if tracking:
            # Parse checkpoints
            checkpoints = tracking.get("checkpoints", [])
            last_checkpoint = checkpoints[-1] if checkpoints else {}

            # Determine status from tag
            tag = tracking.get("tag", "Pending")
            tag_lower = tag.lower().replace(" ", "").replace("_", "") if tag else "pending"
            status_map = {
                "pending": "pending",
                "inforeceived": "pending",
                "infotransit": "in_transit",
                "intransit": "in_transit",
                "outfordelivery": "out_for_delivery",
                "delivered": "delivered",
                "exception": "exception",
                "expired": "expired",
                "attemptfail": "exception",
                "availableforpickup": "out_for_delivery",
            }
            status = status_map.get(tag_lower, "in_transit")

            # Parse dates
            delivered_at = tracking.get("shipment_delivery_date")
            estimated_delivery = None
            edd = tracking.get("courier_estimated_delivery_date") or {}
            if isinstance(edd, dict):
                estimated_delivery = edd.get("estimated_delivery_date")

            result = {
                "success": True,
                "status": status,
                "status_detail": tracking.get("subtag_message", ""),
                "tag": tag,
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
            print(f"{log_prefix} Result: status={status}, tag={tag}, checkpoints={len(checkpoints)}, detail={tracking.get('subtag_message', '')[:50]}")
            return result
        else:
            return {
                "success": False,
                "error": "Could not find or create tracking",
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
