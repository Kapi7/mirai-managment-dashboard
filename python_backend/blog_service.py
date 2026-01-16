"""
Blog Content Generation Service for Mirai Skin

Uses OpenAI GPT-4o to generate SEO-optimized blog articles
for K-Beauty content with human-like writing style.
"""

import os
import json
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict
from openai import OpenAI

# Blog categories with their specific styles
BLOG_CATEGORIES = {
    "lifestyle": {
        "name": "The Mirai Blog",
        "description": "General & Lifestyle - K-Beauty trends, routines, product launches",
        "tone": "Trendy, upbeat, visually driven",
        "structure": "Short paragraphs, lots of headers, listicles welcome",
        "example_topics": [
            "5 Must-Have K-Beauty Trends for the Upcoming Season",
            "Your Ultimate Morning Skincare Routine",
            "How to Build the Perfect Mirai Set for Your Skin Type"
        ],
        "seo_keywords": [
            "K-beauty trends 2026", "Korean skincare routine", "glass skin",
            "dewy skin", "K-beauty products", "skincare routine steps",
            "Korean beauty secrets", "glowing skin tips"
        ]
    },
    "reviews": {
        "name": "Mirai Skin Reviews",
        "description": "Expert Opinions - In-depth product testing with honest results",
        "tone": "Objective, detailed, helpful. Focus on who the product is actually for",
        "structure": "Testing methodology, texture/scent analysis, before/after results, pros/cons, final verdict",
        "example_topics": [
            "We Tried the Medicube Collagen Glow Mask for 30 Days: Here are the Results",
            "Honest Review: Is the COSRX Snail Mucin Worth the Hype?",
            "Beauty of Joseon Dynasty Cream: A Complete Breakdown"
        ],
        "seo_keywords": [
            "honest review", "product review", "before and after",
            "is it worth it", "real results", "tested for 30 days",
            "skincare review", "K-beauty review"
        ]
    },
    "skin_concerns": {
        "name": "Skin Concerns",
        "description": "Educational & Solutions - Help for specific skin conditions",
        "tone": "Empathetic, solution-oriented, accessible. Avoid heavy medical jargon",
        "structure": "Problem identification, causes explained simply, step-by-step solutions, product recommendations",
        "example_topics": [
            "The Gentle Way to Treat Hormonal Acne Without Drying Your Skin",
            "Dehydrated vs Dry Skin: How to Tell the Difference and What to Do",
            "Sensitive Skin? Here's Your Complete K-Beauty Routine"
        ],
        "seo_keywords": [
            "how to treat", "best products for", "gentle skincare",
            "sensitive skin routine", "acne treatment", "dry skin solutions",
            "anti-aging tips", "skin barrier repair"
        ]
    },
    "ingredients": {
        "name": "Ingredients",
        "description": "The K-Beauty Wiki - Deep dives into star ingredients",
        "tone": "Informative and science-backed but exciting. Explain the 'Why' behind ingredients",
        "structure": "What it is, how it works on cellular level (simplified), proven benefits, which products contain it, how to use it",
        "example_topics": [
            "Why Salmon DNA is the Future of Skin Regeneration",
            "Snail Mucin: The Complete Guide to K-Beauty's Hero Ingredient",
            "Niacinamide vs Vitamin C: Which One Should You Choose?"
        ],
        "seo_keywords": [
            "benefits of", "what is", "how to use", "skin regeneration",
            "anti-aging ingredients", "hydrating ingredients",
            "K-beauty ingredients", "skincare science"
        ]
    }
}

# Path for storing drafts
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DRAFTS_FILE = os.path.join(DATA_DIR, "blog_drafts.json")


@dataclass
class BlogDraft:
    id: str
    category: str
    topic: str
    keywords: List[str]
    title: str
    body: str
    meta_description: str
    excerpt: str
    suggested_tags: List[str]
    word_count: int
    status: str  # pending_review, approved, rejected
    created_at: str
    created_by: str
    regeneration_count: int = 0
    regeneration_hints: Optional[str] = None


@dataclass
class PublishedArticle:
    id: str
    draft_id: str
    shopify_article_id: str
    title: str
    category: str
    published_at: str
    shopify_url: str


class BlogStorage:
    """Simple JSON file storage for blog drafts and published articles"""

    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        self._ensure_file_exists()

    def _ensure_file_exists(self):
        if not os.path.exists(DRAFTS_FILE):
            self._save_data({"drafts": [], "published": []})

    def _load_data(self) -> Dict[str, List]:
        try:
            with open(DRAFTS_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {"drafts": [], "published": []}

    def _save_data(self, data: Dict[str, List]):
        with open(DRAFTS_FILE, 'w') as f:
            json.dump(data, f, indent=2)

    def save_draft(self, draft: BlogDraft) -> str:
        data = self._load_data()
        # Check if draft exists (update) or new (insert)
        existing_idx = next((i for i, d in enumerate(data["drafts"]) if d["id"] == draft.id), None)
        if existing_idx is not None:
            data["drafts"][existing_idx] = asdict(draft)
        else:
            data["drafts"].append(asdict(draft))
        self._save_data(data)
        return draft.id

    def get_draft(self, draft_id: str) -> Optional[BlogDraft]:
        data = self._load_data()
        for d in data["drafts"]:
            if d["id"] == draft_id:
                return BlogDraft(**d)
        return None

    def get_all_drafts(self, status: Optional[str] = None) -> List[BlogDraft]:
        data = self._load_data()
        drafts = [BlogDraft(**d) for d in data["drafts"]]
        if status:
            drafts = [d for d in drafts if d.status == status]
        return sorted(drafts, key=lambda x: x.created_at, reverse=True)

    def delete_draft(self, draft_id: str) -> bool:
        data = self._load_data()
        original_len = len(data["drafts"])
        data["drafts"] = [d for d in data["drafts"] if d["id"] != draft_id]
        if len(data["drafts"]) < original_len:
            self._save_data(data)
            return True
        return False

    def save_published(self, article: PublishedArticle):
        data = self._load_data()
        data["published"].append(asdict(article))
        # Remove draft after publishing
        data["drafts"] = [d for d in data["drafts"] if d["id"] != article.draft_id]
        self._save_data(data)

    def get_all_published(self) -> List[PublishedArticle]:
        data = self._load_data()
        articles = [PublishedArticle(**p) for p in data["published"]]
        return sorted(articles, key=lambda x: x.published_at, reverse=True)


class BlogGenerator:
    """AI-powered blog content generator using OpenAI GPT-4o"""

    MAX_REGENERATIONS = 5

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY not configured")
        self.client = OpenAI(api_key=self.api_key)
        self.storage = BlogStorage()

    def _get_system_prompt(self, category: str, keywords: List[str], word_count: int) -> str:
        cat_info = BLOG_CATEGORIES.get(category, BLOG_CATEGORIES["lifestyle"])

        return f"""You are an expert K-Beauty content writer for Mirai Skin, a premium Korean skincare retailer based in Europe.

WRITING RULES (CRITICAL - FOLLOW EXACTLY):
- NEVER use double dashes "--" anywhere in the text
- NEVER use em dashes "—"
- Use commas or periods instead of dashes
- NEVER start sentences with "In the world of", "When it comes to", "In today's", "As we all know"
- NEVER use phrases like "Let's dive in", "Without further ado", "It's no secret that"
- Write naturally like a human beauty editor at Vogue or Allure, not like AI
- Use contractions naturally (we're, you'll, it's, don't, can't)
- Vary sentence length: mix short punchy sentences with longer flowing ones
- Include specific product names when relevant (COSRX, Beauty of Joseon, Medicube, Anua, etc.)
- Be conversational but authoritative
- Write in second person (you, your) to connect with readers
- Add personality and warmth to your writing

CATEGORY: {cat_info['name']}
CATEGORY STYLE: {cat_info['tone']}
ARTICLE STRUCTURE: {cat_info['structure']}

TARGET SEO KEYWORDS (use naturally throughout):
{', '.join(keywords)}

TARGET WORD COUNT: {word_count} words (aim for this, can be slightly more or less)

OUTPUT FORMAT (respond with valid JSON only):
{{
  "title": "SEO-optimized, engaging title that includes the main keyword naturally",
  "meta_description": "Compelling 150-160 character description for search results that includes primary keyword",
  "excerpt": "2-3 sentence hook that makes readers want to click and read more",
  "body": "Full article in clean HTML using only: <h2>, <h3>, <p>, <ul>, <li>, <strong>, <em> tags. No <h1> (title is separate). Include proper spacing between sections.",
  "suggested_tags": ["tag1", "tag2", "tag3", "tag4", "tag5"]
}}

Remember: Write like a passionate K-Beauty enthusiast sharing insider knowledge, not like a corporate blog."""

    def _get_regeneration_prompt(self, original_content: Dict, hints: str) -> str:
        return f"""Please revise this blog article based on the following feedback:

FEEDBACK/HINTS:
{hints}

ORIGINAL ARTICLE:
Title: {original_content['title']}
Body: {original_content['body'][:2000]}...

IMPORTANT: Apply the feedback while maintaining:
- All the writing rules from before (no dashes, natural tone, etc.)
- SEO optimization with the original keywords
- The same output JSON format

Make meaningful improvements based on the feedback. If asked to change tone, adjust throughout. If asked to add sections, integrate them naturally."""

    def generate_article(
        self,
        category: str,
        topic: str,
        keywords: List[str],
        word_count: int = 1000,
        user_email: str = "system"
    ) -> BlogDraft:
        """Generate a new blog article draft"""

        if category not in BLOG_CATEGORIES:
            raise ValueError(f"Invalid category. Must be one of: {list(BLOG_CATEGORIES.keys())}")

        system_prompt = self._get_system_prompt(category, keywords, word_count)
        user_prompt = f"Write a blog article about: {topic}"

        response = self.client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.7,
            max_tokens=4000
        )

        content = json.loads(response.choices[0].message.content)

        # Calculate actual word count
        body_text = content.get("body", "")
        # Strip HTML tags for word count
        import re
        clean_text = re.sub(r'<[^>]+>', '', body_text)
        actual_word_count = len(clean_text.split())

        draft = BlogDraft(
            id=str(uuid.uuid4()),
            category=category,
            topic=topic,
            keywords=keywords,
            title=content.get("title", topic),
            body=content.get("body", ""),
            meta_description=content.get("meta_description", ""),
            excerpt=content.get("excerpt", ""),
            suggested_tags=content.get("suggested_tags", []),
            word_count=actual_word_count,
            status="pending_review",
            created_at=datetime.utcnow().isoformat() + "Z",
            created_by=user_email,
            regeneration_count=0,
            regeneration_hints=None
        )

        self.storage.save_draft(draft)
        return draft

    def regenerate_article(
        self,
        draft_id: str,
        hints: str,
        keep_keywords: bool = True
    ) -> BlogDraft:
        """Regenerate an article with user hints/feedback"""

        draft = self.storage.get_draft(draft_id)
        if not draft:
            raise ValueError(f"Draft not found: {draft_id}")

        if draft.regeneration_count >= self.MAX_REGENERATIONS:
            raise ValueError(f"Maximum regenerations ({self.MAX_REGENERATIONS}) reached for this draft")

        # Build context with original content
        original_content = {
            "title": draft.title,
            "body": draft.body,
            "meta_description": draft.meta_description,
            "excerpt": draft.excerpt
        }

        system_prompt = self._get_system_prompt(draft.category, draft.keywords, draft.word_count)
        regen_prompt = self._get_regeneration_prompt(original_content, hints)

        response = self.client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": regen_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.7,
            max_tokens=4000
        )

        content = json.loads(response.choices[0].message.content)

        # Update draft with new content
        import re
        clean_text = re.sub(r'<[^>]+>', '', content.get("body", ""))

        draft.title = content.get("title", draft.title)
        draft.body = content.get("body", draft.body)
        draft.meta_description = content.get("meta_description", draft.meta_description)
        draft.excerpt = content.get("excerpt", draft.excerpt)
        draft.suggested_tags = content.get("suggested_tags", draft.suggested_tags)
        draft.word_count = len(clean_text.split())
        draft.regeneration_count += 1
        draft.regeneration_hints = hints

        self.storage.save_draft(draft)
        return draft

    def update_draft(
        self,
        draft_id: str,
        title: Optional[str] = None,
        body: Optional[str] = None,
        meta_description: Optional[str] = None,
        excerpt: Optional[str] = None,
        suggested_tags: Optional[List[str]] = None
    ) -> BlogDraft:
        """Manually update a draft's content"""

        draft = self.storage.get_draft(draft_id)
        if not draft:
            raise ValueError(f"Draft not found: {draft_id}")

        if title is not None:
            draft.title = title
        if body is not None:
            draft.body = body
            import re
            clean_text = re.sub(r'<[^>]+>', '', body)
            draft.word_count = len(clean_text.split())
        if meta_description is not None:
            draft.meta_description = meta_description
        if excerpt is not None:
            draft.excerpt = excerpt
        if suggested_tags is not None:
            draft.suggested_tags = suggested_tags

        self.storage.save_draft(draft)
        return draft

    def approve_draft(self, draft_id: str) -> BlogDraft:
        """Mark a draft as approved (ready for publishing)"""
        draft = self.storage.get_draft(draft_id)
        if not draft:
            raise ValueError(f"Draft not found: {draft_id}")
        draft.status = "approved"
        self.storage.save_draft(draft)
        return draft

    def reject_draft(self, draft_id: str) -> bool:
        """Delete a rejected draft"""
        return self.storage.delete_draft(draft_id)

    def record_published(
        self,
        draft_id: str,
        shopify_article_id: str,
        shopify_url: str
    ) -> PublishedArticle:
        """Record that a draft was published to Shopify"""
        draft = self.storage.get_draft(draft_id)
        if not draft:
            raise ValueError(f"Draft not found: {draft_id}")

        article = PublishedArticle(
            id=str(uuid.uuid4()),
            draft_id=draft_id,
            shopify_article_id=shopify_article_id,
            title=draft.title,
            category=draft.category,
            published_at=datetime.utcnow().isoformat() + "Z",
            shopify_url=shopify_url
        )

        self.storage.save_published(article)
        return article

    def get_drafts(self, status: Optional[str] = None) -> List[BlogDraft]:
        """Get all drafts, optionally filtered by status"""
        return self.storage.get_all_drafts(status)

    def get_draft(self, draft_id: str) -> Optional[BlogDraft]:
        """Get a single draft by ID"""
        return self.storage.get_draft(draft_id)

    def get_published(self) -> List[PublishedArticle]:
        """Get all published articles"""
        return self.storage.get_all_published()

    @staticmethod
    def get_categories() -> Dict[str, Any]:
        """Get all blog categories with their metadata"""
        return BLOG_CATEGORIES

    @staticmethod
    def get_seo_keywords(category: str) -> List[str]:
        """Get suggested SEO keywords for a category"""
        cat_info = BLOG_CATEGORIES.get(category)
        if not cat_info:
            return []
        return cat_info.get("seo_keywords", [])


def create_blog_generator(api_key: Optional[str] = None) -> BlogGenerator:
    """Factory function to create a BlogGenerator instance"""
    return BlogGenerator(api_key)


# ============================================================
# INTELLIGENT SEO AGENT
# ============================================================

# Mirai Skin brand voice profile (based on website analysis)
BRAND_VOICE = {
    "tone": "Approachable and educational, yet premium",
    "style": "Friendly, conversational, uses 'you' and 'your' to connect with readers",
    "expertise": "K-Beauty authority with insider knowledge",
    "avoid": [
        "Overly clinical language",
        "AI-sounding phrases",
        "Generic beauty advice",
        "Dashes (-- or —)"
    ],
    "include": [
        "Specific Korean product names",
        "Ingredient science made accessible",
        "Step-by-step guidance",
        "Personal recommendations"
    ]
}

# Trending topics and seasonal content ideas
CONTENT_CALENDAR = {
    "january": ["New Year skincare reset", "Winter hydration", "Glass skin goals"],
    "february": ["Valentine's self-care", "Skin barrier repair", "K-beauty gift guide"],
    "march": ["Spring skin transition", "Brightening routines", "Allergy-season skincare"],
    "april": ["Spring cleaning routine", "Lightweight moisturizers", "Sunscreen guide"],
    "may": ["Pre-summer prep", "Double cleansing", "Vitamin C guide"],
    "june": ["Summer skincare essentials", "Oil control", "Minimal routines"],
    "july": ["Beach-proof skincare", "Cooling products", "Post-sun care"],
    "august": ["Back to basics", "Hydration boosters", "Exfoliation guide"],
    "september": ["Fall transition", "Repair summer damage", "Rich moisturizers"],
    "october": ["Retinol introduction", "Anti-aging routines", "Evening skincare"],
    "november": ["Holiday prep skin", "Gift guides", "Intensive treatments"],
    "december": ["Year-end favorites", "Winter protection", "Self-care rituals"]
}

# Popular K-Beauty ingredients to cover
TRENDING_INGREDIENTS = [
    {"name": "Salmon DNA (PDRN)", "buzz": "hot", "topics": ["regeneration", "anti-aging", "healing"]},
    {"name": "Mugwort", "buzz": "steady", "topics": ["calming", "sensitive skin", "redness"]},
    {"name": "Centella Asiatica", "buzz": "evergreen", "topics": ["healing", "acne scars", "barrier"]},
    {"name": "Snail Mucin", "buzz": "evergreen", "topics": ["hydration", "texture", "glow"]},
    {"name": "Niacinamide", "buzz": "evergreen", "topics": ["pores", "brightening", "oil control"]},
    {"name": "Rice", "buzz": "trending", "topics": ["brightening", "traditional", "gentle"]},
    {"name": "Propolis", "buzz": "steady", "topics": ["acne", "healing", "nourishing"]},
    {"name": "Green Tea", "buzz": "evergreen", "topics": ["antioxidant", "calming", "protection"]},
    {"name": "Hyaluronic Acid", "buzz": "evergreen", "topics": ["hydration", "plumping", "layers"]},
    {"name": "Retinol", "buzz": "hot", "topics": ["anti-aging", "cell turnover", "beginner guide"]},
    {"name": "Vitamin C", "buzz": "evergreen", "topics": ["brightening", "dark spots", "antioxidant"]},
    {"name": "Peptides", "buzz": "trending", "topics": ["firming", "collagen", "anti-aging"]},
    {"name": "Bifida Ferment", "buzz": "trending", "topics": ["microbiome", "barrier", "aging"]}
]


@dataclass
class ContentSuggestion:
    """A smart content suggestion from the SEO agent"""
    id: str
    category: str
    title: str
    topic: str
    keywords: List[str]
    reason: str  # Why this topic was suggested
    priority: str  # high, medium, low
    word_count: int
    estimated_traffic: str  # High, Medium, Low potential
    created_at: str
    status: str  # suggested, generating, ready, dismissed


class SEOAgent:
    """
    Intelligent SEO Agent for Mirai Skin

    Analyzes website content, identifies gaps, and proactively
    generates content suggestions that match the brand voice.
    """

    SUGGESTIONS_FILE = os.path.join(DATA_DIR, "seo_suggestions.json")

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.client = None
        if self.api_key:
            self.client = OpenAI(api_key=self.api_key)
        self.storage = BlogStorage()
        os.makedirs(DATA_DIR, exist_ok=True)

    def _load_suggestions(self) -> List[Dict]:
        try:
            if os.path.exists(self.SUGGESTIONS_FILE):
                with open(self.SUGGESTIONS_FILE, 'r') as f:
                    return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            pass
        return []

    def _save_suggestions(self, suggestions: List[Dict]):
        with open(self.SUGGESTIONS_FILE, 'w') as f:
            json.dump(suggestions, f, indent=2)

    def analyze_content_gaps(self, existing_articles: List[str] = None) -> Dict[str, Any]:
        """
        Analyze what content is missing based on:
        - Existing blog posts
        - Product inventory
        - Trending topics
        - Seasonal relevance
        """
        # Get current month for seasonal suggestions
        current_month = datetime.now().strftime("%B").lower()
        seasonal_topics = CONTENT_CALENDAR.get(current_month, [])

        # Categories that need more content
        gaps = {
            "categories_needing_content": [],
            "trending_ingredients_not_covered": [],
            "seasonal_opportunities": seasonal_topics,
            "evergreen_gaps": []
        }

        # Check which categories have fewer drafts/published
        published = self.storage.get_all_published()
        drafts = self.storage.get_all_drafts()

        category_counts = {cat: 0 for cat in BLOG_CATEGORIES}
        for article in published:
            if article.category in category_counts:
                category_counts[article.category] += 1
        for draft in drafts:
            if draft.category in category_counts:
                category_counts[draft.category] += 1

        # Find underserved categories
        min_count = min(category_counts.values()) if category_counts.values() else 0
        for cat, count in category_counts.items():
            if count <= min_count + 1:  # Within 1 of the minimum
                gaps["categories_needing_content"].append({
                    "category": cat,
                    "name": BLOG_CATEGORIES[cat]["name"],
                    "current_count": count
                })

        # Check trending ingredients not covered recently
        existing_titles = [a.title.lower() for a in published] if existing_articles is None else [a.lower() for a in existing_articles]
        for ingredient in TRENDING_INGREDIENTS:
            ingredient_mentioned = any(ingredient["name"].lower() in title for title in existing_titles)
            if not ingredient_mentioned and ingredient["buzz"] in ["hot", "trending"]:
                gaps["trending_ingredients_not_covered"].append(ingredient)

        return gaps

    def generate_smart_suggestions(self, count: int = 5, force_refresh: bool = False) -> List[ContentSuggestion]:
        """
        Generate intelligent content suggestions based on:
        - Content gap analysis
        - Seasonal trends
        - SEO opportunities
        - Brand voice alignment
        """
        if not self.client:
            raise ValueError("OPENAI_API_KEY required for generating suggestions")

        # Check existing suggestions
        existing = self._load_suggestions()
        active_suggestions = [s for s in existing if s.get("status") not in ["dismissed", "published"]]

        if len(active_suggestions) >= count and not force_refresh:
            return [ContentSuggestion(**s) for s in active_suggestions[:count]]

        # Analyze gaps
        gaps = self.analyze_content_gaps()

        # Build context for AI
        context = f"""You are an SEO content strategist for Mirai Skin, a premium Korean skincare retailer.

BRAND VOICE:
- Tone: {BRAND_VOICE['tone']}
- Style: {BRAND_VOICE['style']}

CONTENT GAPS IDENTIFIED:
- Categories needing content: {json.dumps(gaps['categories_needing_content'])}
- Trending ingredients not covered: {[i['name'] for i in gaps['trending_ingredients_not_covered']]}
- Seasonal opportunities (current month): {gaps['seasonal_opportunities']}

EXISTING BLOG CATEGORIES:
{json.dumps({k: v['name'] + ' - ' + v['description'] for k, v in BLOG_CATEGORIES.items()}, indent=2)}

Generate {count} high-value blog topic suggestions that will:
1. Fill content gaps
2. Target high-traffic SEO keywords
3. Match Mirai Skin's brand voice
4. Provide real value to K-Beauty enthusiasts

For each suggestion, provide:
- A compelling title
- The category it belongs to
- Target SEO keywords (3-5)
- Why this topic will perform well (traffic potential, fills gap, trending, etc.)
- Priority level (high/medium/low)
- Recommended word count (800-1500)

OUTPUT AS JSON ARRAY:
[
  {{
    "title": "Article title",
    "category": "category_key",
    "topic": "Brief description of what the article should cover",
    "keywords": ["keyword1", "keyword2", "keyword3"],
    "reason": "Why this topic was suggested",
    "priority": "high",
    "word_count": 1000,
    "estimated_traffic": "High"
  }}
]"""

        response = self.client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are an expert SEO content strategist. Respond only with valid JSON."},
                {"role": "user", "content": context}
            ],
            response_format={"type": "json_object"},
            temperature=0.8
        )

        result = json.loads(response.choices[0].message.content)
        suggestions_data = result if isinstance(result, list) else result.get("suggestions", [])

        # Convert to ContentSuggestion objects
        suggestions = []
        for item in suggestions_data[:count]:
            suggestion = ContentSuggestion(
                id=str(uuid.uuid4()),
                category=item.get("category", "lifestyle"),
                title=item.get("title", ""),
                topic=item.get("topic", ""),
                keywords=item.get("keywords", []),
                reason=item.get("reason", ""),
                priority=item.get("priority", "medium"),
                word_count=item.get("word_count", 1000),
                estimated_traffic=item.get("estimated_traffic", "Medium"),
                created_at=datetime.utcnow().isoformat() + "Z",
                status="suggested"
            )
            suggestions.append(suggestion)

        # Save suggestions
        all_suggestions = [asdict(s) for s in suggestions] + existing
        self._save_suggestions(all_suggestions)

        return suggestions

    def get_suggestions(self, include_dismissed: bool = False) -> List[ContentSuggestion]:
        """Get all current suggestions"""
        suggestions = self._load_suggestions()
        if not include_dismissed:
            suggestions = [s for s in suggestions if s.get("status") != "dismissed"]
        return [ContentSuggestion(**s) for s in suggestions]

    def dismiss_suggestion(self, suggestion_id: str) -> bool:
        """Mark a suggestion as dismissed"""
        suggestions = self._load_suggestions()
        for s in suggestions:
            if s.get("id") == suggestion_id:
                s["status"] = "dismissed"
                self._save_suggestions(suggestions)
                return True
        return False

    def generate_from_suggestion(self, suggestion_id: str, user_email: str = "system") -> BlogDraft:
        """Generate a full article draft from a suggestion"""
        if not self.client:
            raise ValueError("OPENAI_API_KEY required for generating articles")

        suggestions = self._load_suggestions()
        suggestion = None
        for s in suggestions:
            if s.get("id") == suggestion_id:
                suggestion = s
                break

        if not suggestion:
            raise ValueError(f"Suggestion not found: {suggestion_id}")

        # Update status
        suggestion["status"] = "generating"
        self._save_suggestions(suggestions)

        # Generate the article using BlogGenerator
        generator = BlogGenerator(self.api_key)
        draft = generator.generate_article(
            category=suggestion["category"],
            topic=suggestion["topic"],
            keywords=suggestion["keywords"],
            word_count=suggestion["word_count"],
            user_email=user_email
        )

        # Update suggestion status
        suggestion["status"] = "ready"
        suggestion["draft_id"] = draft.id
        self._save_suggestions(suggestions)

        return draft

    def get_ready_content(self) -> List[Dict[str, Any]]:
        """Get suggestions that have been generated and are ready for review"""
        suggestions = self._load_suggestions()
        ready = []
        for s in suggestions:
            if s.get("status") == "ready" and s.get("draft_id"):
                draft = self.storage.get_draft(s["draft_id"])
                if draft:
                    ready.append({
                        "suggestion": s,
                        "draft": asdict(draft)
                    })
        return ready


def create_seo_agent(api_key: Optional[str] = None) -> SEOAgent:
    """Factory function to create an SEOAgent instance"""
    return SEOAgent(api_key)
