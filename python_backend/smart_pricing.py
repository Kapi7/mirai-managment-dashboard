"""
Smart Pricing Module
Implements intelligent competitor price filtering and pricing algorithms
Based on price-bot logic from /Users/kapi7/price-bot
"""

import statistics
from typing import List, Dict, Optional, Tuple
from datetime import datetime


# Configuration Constants (from price-bot .env)
UNTRUSTED_SELLERS = [
    "mercari", "poshmark", "whatnot", "depop", "facebook marketplace",
    "offerup", "letgo", "craigslist", "ebay/", "aliexpress", "wish",
    "temu", "shein"  # Added common low-quality marketplaces
]

# Outlier Filtering
MIN_COMPETITORS_FOR_FILTERING = 5
OUTLIER_FACTOR = 2.5  # 0.4x to 2.5x median

# Pricing Strategy
TARGET_PROFIT_ON_COST = 0.20  # 20% profit margin
COMPETITOR_UNDERCUT_PCT = 0.03  # Beat competitors by 3%
COMPETITOR_MIN_MARGIN = 0.25  # Never go below 25% margin on COGS
PSP_FEE_RATE = 0.05  # 5% payment processing fee
MAX_COGS_MULTIPLE = 3.0  # Price ceiling: 3x COGS

# Dynamic CPA Bounds
DYNAMIC_CPA_RATE = 0.12  # 12% of estimated retail
DYNAMIC_CPA_MIN = 8.0
DYNAMIC_CPA_MAX = 25.0

# Loss Tolerance
LOSS_OK_UNDER_PRICE = 30.0
LOSS_OK_MAX_LOSS = 10.0


def is_trusted_seller(seller: str) -> bool:
    """
    Check if seller is trusted (not a peer-to-peer marketplace)

    Args:
        seller: Seller name or domain

    Returns:
        bool: True if trusted, False if untrusted
    """
    if not seller:
        return True  # Unknown sellers pass through

    seller_lower = seller.lower()
    return not any(untrusted in seller_lower for untrusted in UNTRUSTED_SELLERS)


def filter_outlier_prices(prices: List[float]) -> List[float]:
    """
    Remove outlier prices using median-based filtering

    Args:
        prices: List of competitor prices

    Returns:
        List[float]: Filtered prices (or original if < 5 prices)
    """
    if len(prices) < MIN_COMPETITORS_FOR_FILTERING:
        return prices  # Not enough data to filter

    if len(prices) == 0:
        return []

    # Calculate median
    median_price = statistics.median(prices)

    # Set thresholds
    min_threshold = median_price / OUTLIER_FACTOR  # 0.4x median
    max_threshold = median_price * OUTLIER_FACTOR  # 2.5x median

    # Filter prices within range
    filtered = [p for p in prices if min_threshold <= p <= max_threshold]

    # Safety: if all prices filtered out, return original
    if len(filtered) == 0:
        return prices

    return filtered


def compute_dynamic_cpa(cogs: float, base_price: float) -> float:
    """
    Calculate dynamic Customer Acquisition Cost based on product value

    Args:
        cogs: Cost of goods sold
        base_price: Current base/retail price

    Returns:
        float: Dynamic CPA (bounded between $8-$25)
    """
    # Estimate retail price (use base_price or estimate from COGS)
    estimated_retail = base_price if base_price > 0 else cogs * 2.5

    # Calculate dynamic CPA as 12% of retail
    dynamic_cpa = estimated_retail * DYNAMIC_CPA_RATE

    # Apply bounds
    return max(DYNAMIC_CPA_MIN, min(dynamic_cpa, DYNAMIC_CPA_MAX))


def compute_suggested_price(
    cogs: float,
    shipping: float,
    base_price: float,
    cpa: Optional[float] = None
) -> Tuple[float, float, float]:
    """
    Calculate three-tier pricing: breakeven, target profit, suggested

    Args:
        cogs: Cost of goods sold
        shipping: Shipping cost
        base_price: Current base/retail price
        cpa: Customer acquisition cost (optional, will calculate if not provided)

    Returns:
        Tuple[float, float, float]: (breakeven_relaxed, target_profit, suggested)
    """
    # Calculate dynamic CPA if not provided
    if cpa is None:
        cpa = compute_dynamic_cpa(cogs, base_price)

    # Total cost
    total_cost = cogs + cpa + shipping

    # For low-COGS items, allow $5 loss for marketing
    relaxed_cost = max(total_cost - 5.0, 0) if cogs < 10 else total_cost

    # Breakeven (accounting for PSP fee)
    breakeven_relaxed = relaxed_cost / (1 - PSP_FEE_RATE)

    # Target profit (20% on total cost)
    target_profit = (1 + TARGET_PROFIT_ON_COST) * total_cost / (1 - PSP_FEE_RATE)

    # Suggested price (capped at 3x COGS)
    price_cap = cogs * MAX_COGS_MULTIPLE
    suggested = max(breakeven_relaxed, min(target_profit, price_cap))

    return breakeven_relaxed, target_profit, suggested


def compute_competitive_price(
    suggested: float,
    comp_low: Optional[float],
    comp_avg: Optional[float],
    comp_high: Optional[float],
    cogs: float
) -> Tuple[float, str]:
    """
    Calculate competitive price by undercutting average by 3%
    while maintaining 25% minimum margin

    Args:
        suggested: Suggested price from profit calculations
        comp_low: Competitor low price
        comp_avg: Competitor average price
        comp_high: Competitor high price
        cogs: Cost of goods sold

    Returns:
        Tuple[float, str]: (final_price, note)
    """
    # No competitor data
    if not comp_avg or comp_avg <= 0:
        return suggested, "No competitor data"

    # Calculate minimum acceptable price (25% margin floor)
    min_price = cogs * (1 + COMPETITOR_MIN_MARGIN)

    # Calculate competitive target (beat average by 3%)
    target = comp_avg * (1 - COMPETITOR_UNDERCUT_PCT)

    # Decision logic
    if target < min_price:
        return min_price, f"Floor price (can't beat avg profitably)"
    elif suggested <= target:
        return suggested, "Already competitive"
    else:
        return target, f"Undercut avg by {COMPETITOR_UNDERCUT_PCT*100:.0f}%"


def compute_status_vs_current(
    current_price: float,
    cogs: float,
    shipping: float,
    base_price: float,
    cpa: Optional[float] = None
) -> Tuple[str, float]:
    """
    Determine profitability status of current price

    Args:
        current_price: Current selling price
        cogs: Cost of goods sold
        shipping: Shipping cost
        base_price: Base retail price
        cpa: Customer acquisition cost (optional)

    Returns:
        Tuple[str, float]: (status, profit_amount)

    Status codes:
        - "NO_PRICE": No price set
        - "OK": Profitable
        - "LOSS_OK": Small acceptable loss
        - "TOO_LOW": Losing too much money
    """
    if current_price <= 0:
        return "NO_PRICE", 0.0

    # Calculate dynamic CPA if not provided
    if cpa is None:
        cpa = compute_dynamic_cpa(cogs, base_price)

    # Calculate profit
    net_revenue = current_price * (1 - PSP_FEE_RATE)
    total_cost = cogs + cpa + shipping
    profit = net_revenue - total_cost

    # Status determination
    if profit >= 0:
        return "OK", profit

    # Check if loss is acceptable
    loss_amount = abs(profit)
    if current_price < LOSS_OK_UNDER_PRICE and loss_amount <= LOSS_OK_MAX_LOSS:
        return "LOSS_OK", profit

    return "TOO_LOW", profit


def compute_priority(status: str, loss_amount: float) -> str:
    """
    Compute action priority based on status and loss

    Args:
        status: Profitability status
        loss_amount: Dollar amount of profit/loss

    Returns:
        str: "HIGH" | "MEDIUM" | "LOW" | "OK"
    """
    if status in ["NO_PRICE", "TOO_LOW"]:
        return "HIGH"

    if status == "LOSS_OK":
        return "MEDIUM"

    # Positive profit
    if loss_amount < 5.0:  # Less than $5 profit
        return "LOW"

    return "OK"


def analyze_competitor_prices(
    prices_with_sellers: List[Dict[str, any]]
) -> Dict[str, any]:
    """
    Analyze competitor prices with smart filtering

    Args:
        prices_with_sellers: List of {price: float, seller: str, domain: str, ...}

    Returns:
        Dict with keys:
            - raw_count: Original number of prices
            - trusted_count: After trusted seller filter
            - filtered_count: After outlier removal
            - comp_low: Minimum price
            - comp_avg: Average price
            - comp_high: Maximum price
            - prices: Final filtered prices
    """
    if not prices_with_sellers:
        return {
            "raw_count": 0,
            "trusted_count": 0,
            "filtered_count": 0,
            "comp_low": None,
            "comp_avg": None,
            "comp_high": None,
            "prices": []
        }

    # Extract prices
    all_prices = [p["price"] for p in prices_with_sellers if p.get("price", 0) > 0]
    raw_count = len(all_prices)

    # Filter by trusted sellers
    trusted_prices = [
        p["price"] for p in prices_with_sellers
        if p.get("price", 0) > 0 and is_trusted_seller(p.get("seller", ""))
    ]
    trusted_count = len(trusted_prices)

    # Remove outliers
    filtered_prices = filter_outlier_prices(trusted_prices)
    filtered_count = len(filtered_prices)

    # Calculate statistics
    if filtered_prices:
        comp_low = min(filtered_prices)
        comp_avg = statistics.mean(filtered_prices)
        comp_high = max(filtered_prices)
    else:
        comp_low = comp_avg = comp_high = None

    return {
        "raw_count": raw_count,
        "trusted_count": trusted_count,
        "filtered_count": filtered_count,
        "comp_low": comp_low,
        "comp_avg": comp_avg,
        "comp_high": comp_high,
        "prices": filtered_prices
    }


def calculate_complete_pricing(
    variant_id: str,
    item_name: str,
    cogs: float,
    shipping: float,
    current_price: float,
    competitor_prices: List[Dict[str, any]]
) -> Dict[str, any]:
    """
    Complete pricing calculation with competitive analysis

    Args:
        variant_id: Product variant ID
        item_name: Product name
        cogs: Cost of goods sold
        shipping: Shipping cost
        current_price: Current selling price
        competitor_prices: List of competitor price dicts

    Returns:
        Dict with complete pricing analysis
    """
    # Analyze competitor prices with smart filtering
    comp_analysis = analyze_competitor_prices(competitor_prices)

    # Calculate dynamic CPA
    dynamic_cpa = compute_dynamic_cpa(cogs, current_price)

    # Calculate suggested prices
    breakeven, target, suggested = compute_suggested_price(
        cogs, shipping, current_price, dynamic_cpa
    )

    # Calculate competitive price
    final_suggested, comp_note = compute_competitive_price(
        suggested,
        comp_analysis["comp_low"],
        comp_analysis["comp_avg"],
        comp_analysis["comp_high"],
        cogs
    )

    # Analyze current price status
    status, profit = compute_status_vs_current(
        current_price, cogs, shipping, current_price, dynamic_cpa
    )

    # Compute priority
    priority = compute_priority(status, profit)

    return {
        "variant_id": variant_id,
        "item": item_name,
        "cogs": cogs,
        "shipping": shipping,
        "dynamic_cpa": dynamic_cpa,
        "current_price": current_price,
        "breakeven_price": breakeven,
        "target_price": target,
        "suggested_price": suggested,
        "final_suggested_price": final_suggested,
        "competitive_note": comp_note,
        "status": status,
        "profit_loss": profit,
        "priority": priority,
        "competitor_analysis": comp_analysis,
        "timestamp": datetime.utcnow().isoformat()
    }
