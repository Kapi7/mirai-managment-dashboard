# shopify_client.py — GraphQL helpers (orders + shop timezone) + multi-store support
from __future__ import annotations

import os
import time
import requests
from typing import List, Dict, Any, Optional

from dotenv import load_dotenv

load_dotenv()

# Pull from ENV to avoid circular imports with config.py
SHOPIFY_STORE = (os.getenv("SHOPIFY_STORE") or "").strip()
SHOPIFY_ACCESS_TOKEN = (os.getenv("SHOPIFY_ACCESS_TOKEN") or "").strip()
SHOPIFY_API_VERSION = (os.getenv("SHOPIFY_API_VERSION") or "2025-07").strip() or "2025-07"

# Default (main) store base — used by legacy single-store functions
BASE = f"https://{SHOPIFY_STORE}/admin/api/{SHOPIFY_API_VERSION}" if SHOPIFY_STORE else ""
GQL_URL = f"{BASE}/graphql.json" if BASE else ""


def _headers_for(access_token: str) -> Dict[str, str]:
    return {
        "X-Shopify-Access-Token": access_token,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _headers() -> Dict[str, str]:
    return _headers_for(SHOPIFY_ACCESS_TOKEN)


def _gql(
    query: str,
    variables: Optional[Dict[str, Any]] = None,
    *,
    retries: int = 3,
    backoff: float = 1.0,
) -> Dict[str, Any]:
    """GraphQL against the default store."""
    if not GQL_URL:
        raise RuntimeError("SHOPIFY_STORE is not set (SHOPIFY_STORE env var).")
    if not SHOPIFY_ACCESS_TOKEN:
        raise RuntimeError("SHOPIFY_ACCESS_TOKEN is not set (SHOPIFY_ACCESS_TOKEN env var).")

    attempt = 0
    cur_backoff = backoff
    while True:
        try:
            r = requests.post(
                GQL_URL,
                json={"query": query, "variables": variables or {}},
                headers=_headers(),
                timeout=60,
            )
            if r.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"{r.status_code}: {r.text}")
            r.raise_for_status()
            data = r.json()
            if data.get("errors"):
                raise RuntimeError(data["errors"])
            return data["data"]
        except Exception:
            attempt += 1
            if attempt > retries:
                raise
            time.sleep(cur_backoff)
            cur_backoff = min(8.0, cur_backoff * 2)


def _gql_for(
    store_domain: str,
    access_token: str,
    query: str,
    variables: Optional[Dict[str, Any]] = None,
    *,
    retries: int = 3,
    backoff: float = 1.0,
) -> Dict[str, Any]:
    """GraphQL helper for an arbitrary store (domain + token)."""
    store_domain = (store_domain or "").strip()
    access_token = (access_token or "").strip()
    if not store_domain:
        raise RuntimeError("store_domain is empty")
    if not access_token:
        raise RuntimeError(f"access_token missing for store {store_domain}")

    base = f"https://{store_domain}/admin/api/{SHOPIFY_API_VERSION}"
    gql_url = f"{base}/graphql.json"
    headers = _headers_for(access_token)

    attempt = 0
    cur_backoff = backoff
    while True:
        try:
            r = requests.post(
                gql_url,
                json={"query": query, "variables": variables or {}},
                headers=headers,
                timeout=60,
            )
            if r.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"{r.status_code}: {r.text}")
            r.raise_for_status()
            data = r.json()
            if data.get("errors"):
                raise RuntimeError(data["errors"])
            return data["data"]
        except Exception:
            attempt += 1
            if attempt > retries:
                raise
            time.sleep(cur_backoff)
            cur_backoff = min(8.0, cur_backoff * 2)


def get_shop_timezone() -> Optional[str]:
    """Timezone of the *default* store (SHOPIFY_STORE)."""
    q = "query { shop { ianaTimezone } }"
    try:
        data = _gql(q, {})
        return (data.get("shop") or {}).get("ianaTimezone")
    except Exception:
        return None


def get_shop_timezone_for_store(store_domain: str, access_token: str) -> Optional[str]:
    """Timezone of a specific store."""
    q = "query { shop { ianaTimezone } }"
    try:
        data = _gql_for(store_domain, access_token, q, {})
        return (data.get("shop") or {}).get("ianaTimezone")
    except Exception:
        return None


# Orders query: includes everything needed by reporting & alerts
# IMPORTANT: Shopify 2025-07 does NOT have customerJourneySummary.{firstVisit,lastVisit}.landingPageUrl
ORDERS_GQL = """
query Orders($cursor: String, $search: String!) {
  orders(first: 250, after: $cursor, query: $search, sortKey: CREATED_AT, reverse: false) {
    pageInfo { hasNextPage }
    edges {
      cursor
      node {
        id
        name
        createdAt
        processedAt
        cancelledAt
        test
        displayFinancialStatus
        sourceName
        customer { id email numberOfOrders }

        # GEO + weight
        shippingAddress { country countryCodeV2 }
        billingAddress  { country countryCodeV2 }
        totalWeight

        # Marketing channel / UTM
        customerJourneySummary {
          firstVisit {
            utmParameters { source medium campaign content term }
            referrerUrl
          }
          lastVisit  {
            utmParameters { source medium campaign content term }
            referrerUrl
          }
        }

        # Day aggregation
        currentTotalDiscountsSet { shopMoney { amount currencyCode } }
        totalDiscountsSet       { shopMoney { amount currencyCode } }
        totalRefundedSet        { shopMoney { amount currencyCode } }
        currentShippingPriceSet { shopMoney { amount currencyCode } }
        totalShippingPriceSet   { shopMoney { amount currencyCode } }

        lineItems(first: 250) {
          nodes {
            quantity
            originalTotalSet { shopMoney { amount currencyCode } }
            sku
            variant {
              id
              title
              sku
              inventoryItem { unitCost { amount currencyCode } }
              product { id title }
            }
          }
        }
      }
    }
  }
}
"""


def _dedupe_by_id(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out, seen = [], set()
    for o in nodes:
        oid = o.get("id")
        if not oid or oid in seen:
            continue
        seen.add(oid)
        out.append(o)
    return out


def _search_orders(search: str) -> List[Dict[str, Any]]:
    """Search orders in the default store."""
    vars_ = {"cursor": None, "search": search}
    nodes: List[Dict[str, Any]] = []
    while True:
        data = _gql(ORDERS_GQL, vars_)
        orders = (data.get("orders") or {})
        edges = orders.get("edges") or []
        nodes.extend([e["node"] for e in edges if isinstance(e, dict) and "node" in e])
        if not (orders.get("pageInfo") or {}).get("hasNextPage"):
            break
        vars_["cursor"] = edges[-1]["cursor"]
    return _dedupe_by_id(nodes)


def _search_orders_for(store_domain: str, access_token: str, search: str) -> List[Dict[str, Any]]:
    """Search orders in a specific store."""
    vars_ = {"cursor": None, "search": search}
    nodes: List[Dict[str, Any]] = []
    while True:
        data = _gql_for(store_domain, access_token, ORDERS_GQL, vars_)
        orders = (data.get("orders") or {})
        edges = orders.get("edges") or []
        nodes.extend([e["node"] for e in edges if isinstance(e, dict) and "node" in e])
        if not (orders.get("pageInfo") or {}).get("hasNextPage"):
            break
        vars_["cursor"] = edges[-1]["cursor"]
    return _dedupe_by_id(nodes)


# ---------- existing single-store helpers (main store) ----------

def fetch_orders_created_between(start_iso: str, end_iso: str, *, exclude_cancelled: bool = True) -> List[Dict[str, Any]]:
    """Main store: created_at in [start_iso, end_iso)."""
    terms = [f"created_at:>={start_iso}", f"created_at:<{end_iso}"]
    if exclude_cancelled:
        terms.append("-cancelled_at:*")
    out = _search_orders(" ".join(terms))
    if exclude_cancelled:
        out = [o for o in out if not o.get("cancelledAt")]
    return out


def fetch_orders_processed_between(start_iso: str, end_iso: str, *, exclude_cancelled: bool = True) -> List[Dict[str, Any]]:
    """Main store: processed_at in [start_iso, end_iso)."""
    terms = [f"processed_at:>={start_iso}", f"processed_at:<{end_iso}"]
    if exclude_cancelled:
        terms.append("-cancelled_at:*")
    out = _search_orders(" ".join(terms))
    if exclude_cancelled:
        out = [o for o in out if not o.get("cancelledAt")]
    return out


# ---------- per-store variants (used by master aggregation) ----------

def fetch_orders_created_between_for_store(
    store_domain: str,
    access_token: str,
    start_iso: str,
    end_iso: str,
    *,
    exclude_cancelled: bool = True,
) -> List[Dict[str, Any]]:
    terms = [f"created_at:>={start_iso}", f"created_at:<{end_iso}"]
    if exclude_cancelled:
        terms.append("-cancelled_at:*")
    out = _search_orders_for(store_domain, access_token, " ".join(terms))
    if exclude_cancelled:
        out = [o for o in out if not o.get("cancelledAt")]
    return out


def fetch_orders_processed_between_for_store(
    store_domain: str,
    access_token: str,
    start_iso: str,
    end_iso: str,
    *,
    exclude_cancelled: bool = True,
) -> List[Dict[str, Any]]:
    terms = [f"processed_at:>={start_iso}", f"processed_at:<{end_iso}"]
    if exclude_cancelled:
        terms.append("-cancelled_at:*")
    out = _search_orders_for(store_domain, access_token, " ".join(terms))
    if exclude_cancelled:
        out = [o for o in out if not o.get("cancelledAt")]
    return out


# ---- helpers used by analyze_order.py ----

def fetch_order_addresses_by_name(order_name: str) -> Optional[dict]:
    q = """
    query One($search: String!) {
      orders(first: 1, query: $search) {
        edges {
          node {
            id
            name
            shippingAddress { country countryCodeV2 }
            billingAddress  { country countryCodeV2 }
          }
        }
      }
    }
    """
    data = _gql(q, {"search": f'name:"#{order_name}"'})
    edges = ((data.get("orders") or {}).get("edges") or [])
    if not edges:
        return None
    node = edges[0].get("node") or {}
    return {
        "shippingAddress": node.get("shippingAddress") or {},
        "billingAddress": node.get("billingAddress") or {},
    }


def fetch_variant_unit_cost_usd_by_gid(variant_gid: str) -> Optional[float]:
    q = """
    query Vcost($id: ID!) {
      productVariant(id: $id) {
        inventoryItem { unitCost { amount currencyCode } }
      }
    }
    """
    try:
        data = _gql(q, {"id": variant_gid})
        inv = (((data.get("productVariant") or {}).get("inventoryItem")) or {})
        uc  = (inv.get("unitCost") or {})
        amt = uc.get("amount")
        if amt is None:
            return None
        return float(amt)
    except Exception:
        return None


# ---------- Blog API Functions ----------

BLOGS_GQL = """
query GetBlogs($first: Int!) {
  blogs(first: $first) {
    edges {
      node {
        id
        title
        handle
      }
    }
  }
}
"""

ARTICLES_GQL = """
query GetArticles($blogId: ID!, $first: Int!, $cursor: String) {
  blog(id: $blogId) {
    id
    title
    articles(first: $first, after: $cursor, sortKey: PUBLISHED_AT, reverse: true) {
      pageInfo { hasNextPage }
      edges {
        cursor
        node {
          id
          title
          handle
          publishedAt
          author { name }
          tags
          excerpt: summary
          onlineStoreUrl
          image { url altText }
        }
      }
    }
  }
}
"""

CREATE_ARTICLE_MUTATION = """
mutation CreateArticle($blogId: ID!, $input: ArticleInput!) {
  articleCreate(blogId: $blogId, article: $input) {
    article {
      id
      title
      handle
      publishedAt
      onlineStoreUrl
    }
    userErrors {
      field
      message
    }
  }
}
"""

UPDATE_ARTICLE_MUTATION = """
mutation UpdateArticle($id: ID!, $input: ArticleInput!) {
  articleUpdate(id: $id, article: $input) {
    article {
      id
      title
      handle
      publishedAt
      onlineStoreUrl
    }
    userErrors {
      field
      message
    }
  }
}
"""


def fetch_blogs(limit: int = 50) -> List[Dict[str, Any]]:
    """Fetch all blogs from the default store."""
    try:
        data = _gql(BLOGS_GQL, {"first": limit})
        edges = (data.get("blogs") or {}).get("edges") or []
        return [e["node"] for e in edges if isinstance(e, dict) and "node" in e]
    except Exception as e:
        print(f"[shopify_client] Error fetching blogs: {e}")
        return []


def fetch_articles(blog_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Fetch articles from a specific blog."""
    all_articles = []
    cursor = None

    while True:
        try:
            data = _gql(ARTICLES_GQL, {"blogId": blog_id, "first": min(limit, 50), "cursor": cursor})
            blog_data = data.get("blog") or {}
            articles_data = blog_data.get("articles") or {}
            edges = articles_data.get("edges") or []

            for edge in edges:
                if isinstance(edge, dict) and "node" in edge:
                    all_articles.append(edge["node"])

            page_info = articles_data.get("pageInfo") or {}
            if not page_info.get("hasNextPage") or len(all_articles) >= limit:
                break

            cursor = edges[-1]["cursor"] if edges else None
        except Exception as e:
            print(f"[shopify_client] Error fetching articles: {e}")
            break

    return all_articles[:limit]


def fetch_all_articles(limit: int = 100) -> List[Dict[str, Any]]:
    """Fetch articles from all blogs."""
    blogs = fetch_blogs()
    all_articles = []

    for blog in blogs:
        blog_id = blog.get("id")
        if blog_id:
            articles = fetch_articles(blog_id, limit=limit)
            for article in articles:
                article["blog_title"] = blog.get("title", "Unknown")
                article["blog_id"] = blog_id
            all_articles.extend(articles)

    # Sort by published date
    all_articles.sort(key=lambda x: x.get("publishedAt") or "", reverse=True)
    return all_articles[:limit]


def create_article(
    blog_id: str,
    title: str,
    body_html: str,
    author: str = "Mirai Skin Team",
    tags: Optional[List[str]] = None,
    published: bool = True,
    summary: Optional[str] = None
) -> Dict[str, Any]:
    """Create a new article in a blog."""
    input_data = {
        "title": title,
        "body": body_html,
        "author": {"name": author},
        "isPublished": published,
    }

    if tags:
        input_data["tags"] = tags

    if summary:
        input_data["summary"] = summary

    try:
        data = _gql(CREATE_ARTICLE_MUTATION, {"blogId": blog_id, "input": input_data})
        result = data.get("articleCreate") or {}
        errors = result.get("userErrors") or []

        if errors:
            error_messages = [f"{e.get('field')}: {e.get('message')}" for e in errors]
            raise RuntimeError(f"Failed to create article: {'; '.join(error_messages)}")

        article = result.get("article") or {}
        return {
            "success": True,
            "article_id": article.get("id"),
            "title": article.get("title"),
            "handle": article.get("handle"),
            "url": article.get("onlineStoreUrl"),
            "published_at": article.get("publishedAt")
        }
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Failed to create article: {str(e)}")


def update_article(
    article_id: str,
    title: Optional[str] = None,
    body_html: Optional[str] = None,
    author: Optional[str] = None,
    tags: Optional[List[str]] = None,
    published: Optional[bool] = None,
    summary: Optional[str] = None
) -> Dict[str, Any]:
    """Update an existing article."""
    input_data = {}

    if title is not None:
        input_data["title"] = title
    if body_html is not None:
        input_data["body"] = body_html
    if author is not None:
        input_data["author"] = {"name": author}
    if tags is not None:
        input_data["tags"] = tags
    if published is not None:
        input_data["isPublished"] = published
    if summary is not None:
        input_data["summary"] = summary

    if not input_data:
        raise ValueError("No fields to update")

    try:
        data = _gql(UPDATE_ARTICLE_MUTATION, {"id": article_id, "input": input_data})
        result = data.get("articleUpdate") or {}
        errors = result.get("userErrors") or []

        if errors:
            error_messages = [f"{e.get('field')}: {e.get('message')}" for e in errors]
            raise RuntimeError(f"Failed to update article: {'; '.join(error_messages)}")

        article = result.get("article") or {}
        return {
            "success": True,
            "article_id": article.get("id"),
            "title": article.get("title"),
            "handle": article.get("handle"),
            "url": article.get("onlineStoreUrl"),
            "published_at": article.get("publishedAt")
        }
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Failed to update article: {str(e)}")
