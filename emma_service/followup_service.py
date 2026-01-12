"""
Proactive Delivery Follow-up Service

Automatically sends personalized follow-up emails when packages are delivered.
Recommends complementary products based on what the customer ordered.
"""

import os
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from openai import OpenAI

# Product recommendations based on categories
PRODUCT_RECOMMENDATIONS = {
    # If they bought cleansers, recommend toners/essences
    "cleanser": ["toner", "essence", "serum", "moisturizer"],
    "foam": ["toner", "essence", "serum"],
    "gel cleanser": ["toner", "essence", "micellar"],

    # If they bought toners, recommend serums
    "toner": ["serum", "essence", "ampoule", "moisturizer"],
    "essence": ["serum", "ampoule", "cream"],

    # If they bought serums, recommend moisturizers
    "serum": ["moisturizer", "cream", "sleeping mask", "eye cream"],
    "ampoule": ["moisturizer", "cream", "sleeping mask"],

    # If they bought moisturizers, recommend SPF or treatments
    "moisturizer": ["sunscreen", "spf", "sleeping mask", "eye cream"],
    "cream": ["sunscreen", "eye cream", "sleeping mask"],

    # If they bought sunscreen, recommend cleansers (for removal)
    "sunscreen": ["cleanser", "cleansing oil", "micellar water"],
    "spf": ["cleanser", "cleansing balm"],

    # Masks
    "sheet mask": ["essence", "serum", "sleeping mask"],
    "mask": ["toner", "essence", "moisturizer"],

    # Eye care
    "eye cream": ["serum", "sleeping mask", "mask"],
    "eye patch": ["eye cream", "serum"],

    # Lip care
    "lip": ["lip mask", "lip balm", "lip treatment"],

    # Foundation/makeup
    "foundation": ["primer", "setting spray", "cushion", "concealer"],
    "cushion": ["primer", "setting powder", "concealer"],
    "bb cream": ["primer", "sunscreen", "setting spray"],
}

# Popular Mirai products for recommendations
POPULAR_PRODUCTS = [
    {"name": "COSRX Advanced Snail 96 Mucin Power Essence", "category": "essence", "concern": "hydration"},
    {"name": "Beauty of Joseon Glow Serum", "category": "serum", "concern": "brightening"},
    {"name": "SKIN1004 Madagascar Centella Ampoule", "category": "ampoule", "concern": "soothing"},
    {"name": "Innisfree Green Tea Seed Serum", "category": "serum", "concern": "hydration"},
    {"name": "COSRX Low pH Good Morning Gel Cleanser", "category": "cleanser", "concern": "gentle"},
    {"name": "Klairs Supple Preparation Toner", "category": "toner", "concern": "hydration"},
    {"name": "MISSHA Time Revolution First Treatment Essence", "category": "essence", "concern": "anti-aging"},
    {"name": "Etude House SoonJung pH 5.5 Relief Toner", "category": "toner", "concern": "sensitive"},
    {"name": "PURITO Centella Green Level Buffet Serum", "category": "serum", "concern": "soothing"},
    {"name": "Isntree Hyaluronic Acid Toner", "category": "toner", "concern": "hydration"},
]


def get_complementary_products(ordered_items: List[str]) -> List[Dict]:
    """
    Get complementary product recommendations based on what customer ordered.
    """
    recommendations = set()

    # Find categories of ordered items
    ordered_lower = [item.lower() for item in ordered_items]

    for item in ordered_lower:
        for category, recs in PRODUCT_RECOMMENDATIONS.items():
            if category in item:
                recommendations.update(recs)

    # If no specific matches, recommend popular items
    if not recommendations:
        recommendations = {"serum", "essence", "moisturizer"}

    # Filter popular products that match recommendations
    matching_products = []
    for product in POPULAR_PRODUCTS:
        if product["category"] in recommendations:
            # Don't recommend what they already bought
            already_has = any(product["name"].lower() in item for item in ordered_lower)
            if not already_has:
                matching_products.append(product)

    return matching_products[:3]  # Return top 3


def generate_followup_email(
    customer_name: str,
    customer_email: str,
    order_number: str,
    ordered_items: List[str],
    delivered_date: datetime = None,
) -> Dict[str, str]:
    """
    Generate a personalized follow-up email after delivery.

    Returns:
        {
            "subject": str,
            "body": str,
            "recommendations": list
        }
    """
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    # Get product recommendations
    recommendations = get_complementary_products(ordered_items)
    rec_text = "\n".join([f"- {p['name']}" for p in recommendations]) if recommendations else ""

    first_name = customer_name.split()[0] if customer_name else "there"
    items_text = ", ".join(ordered_items[:3])
    if len(ordered_items) > 3:
        items_text += f" and {len(ordered_items) - 3} more items"

    prompt = f"""Write a short, warm follow-up email from Emma at Mirai Skin to a customer whose order was just delivered.

Customer: {first_name}
Order: #{order_number}
Items: {items_text}

Guidelines:
- Be warm and genuine, not salesy
- Ask how they're enjoying their products
- Mention we're here if they have questions about their skincare routine
- Briefly mention complementary products they might like (don't be pushy)
- Keep it SHORT - 3-4 sentences max
- Sign off as Emma

Recommended products to mention (pick 1-2 naturally):
{rec_text}

Write ONLY the email body, no subject line. Keep it conversational and brief."""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
            temperature=0.7,
        )

        body = response.choices[0].message.content.strip()

        # Generate subject
        subject = f"How are you enjoying your order, {first_name}? 💕"

        return {
            "subject": subject,
            "body": body,
            "recommendations": recommendations,
            "success": True,
        }

    except Exception as e:
        print(f"[followup_service] Error generating email: {e}")

        # Fallback template
        return {
            "subject": f"Your Mirai order has arrived! 🎉",
            "body": f"""Hi {first_name}!

I hope you're loving your new skincare goodies! If you have any questions about how to use your products or need routine tips, I'm here to help.

Looking forward to hearing how it's working for you!

Warmly,
Emma""",
            "recommendations": recommendations,
            "success": True,
        }


def send_followup_email(
    to_email: str,
    subject: str,
    body: str,
) -> Dict[str, Any]:
    """
    Send the follow-up email via Gmail OAuth (through Node.js API).
    """
    import requests

    # Get the dashboard URL to call the send-email endpoint
    dashboard_url = os.getenv("MIRAI_DASHBOARD_URL", "http://localhost:5001")

    # Build HTML version
    html_body = body.replace('\n', '<br>')
    html = f"""
    <html>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
            {html_body}
            <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
            <p style="font-size: 12px; color: #888;">
                Mirai Skin - Korean Beauty, Delivered<br>
                <a href="https://mirai-skin.com" style="color: #888;">mirai-skin.com</a>
            </p>
        </div>
    </body>
    </html>
    """

    try:
        response = requests.post(
            f"{dashboard_url}/api/send-email",
            json={
                "to": to_email,
                "subject": subject,
                "body": body,
                "html": html,
                "from_name": "Emma R"
            },
            timeout=30
        )

        if response.ok:
            data = response.json()
            if data.get("success"):
                print(f"[followup_service] Email sent to {to_email} (messageId: {data.get('messageId')})")
                return {"success": True, "message": f"Followup sent to {to_email}", "messageId": data.get("messageId")}
            else:
                return {"success": False, "error": data.get("error", "Unknown error")}
        else:
            return {"success": False, "error": f"HTTP {response.status_code}: {response.text[:200]}"}

    except Exception as e:
        print(f"[followup_service] Error sending email: {e}")
        return {"success": False, "error": str(e)}


def process_delivery_followup(
    customer_email: str,
    customer_name: str,
    order_number: str,
    ordered_items: List[str],
    delivered_date: datetime = None,
    send_email: bool = True,
) -> Dict[str, Any]:
    """
    Full process: generate and optionally send follow-up email.

    Returns:
        {
            "success": bool,
            "email_generated": dict,
            "email_sent": bool,
            "error": str (if any)
        }
    """
    # Generate the email
    email_content = generate_followup_email(
        customer_name=customer_name,
        customer_email=customer_email,
        order_number=order_number,
        ordered_items=ordered_items,
        delivered_date=delivered_date,
    )

    result = {
        "success": True,
        "email_generated": email_content,
        "email_sent": False,
    }

    if send_email and email_content.get("success"):
        send_result = send_followup_email(
            to_email=customer_email,
            subject=email_content["subject"],
            body=email_content["body"],
        )
        result["email_sent"] = send_result.get("success", False)
        if not send_result.get("success"):
            result["send_error"] = send_result.get("error")

    return result


if __name__ == "__main__":
    # Test the service
    from dotenv import load_dotenv
    load_dotenv("../.env")

    result = generate_followup_email(
        customer_name="Christina Pan",
        customer_email="test@example.com",
        order_number="2191",
        ordered_items=["ETUDE HOUSE Double Lasting Foundation SPF34 PA++"],
    )

    print("Generated Email:")
    print(f"Subject: {result['subject']}")
    print(f"\nBody:\n{result['body']}")
    print(f"\nRecommendations: {result['recommendations']}")
