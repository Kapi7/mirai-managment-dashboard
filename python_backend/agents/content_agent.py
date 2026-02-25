"""
Content Agent — Agent 2 in the CMO hierarchy.

Creates ALL content (text, images, video) as reusable assets shared across
organic social media and paid ads.  Wraps existing services:
    - SocialMediaAgent  (image / video generation)
    - BlogGenerator     (blog articles)
    - SEOAgent          (content-gap analysis)

Every generated piece is persisted via ContentAssetStore so it can be reused
by the Social and Acquisition agents downstream.

Task types:
    create_social_asset       — image + caption for organic social
    create_ad_creative        — ad-optimised asset (punchier headline, CTA)
    create_blog_article       — blog article via BlogGenerator
    create_multi_format_asset — ONE concept → image, video, IG/TikTok/ad/blog text
    create_enhanced_video     — multi-take Veo 2 pipeline with frame-by-frame prompts
    analyze_content_gaps      — gap analysis via SEOAgent + follow-up task creation
"""

import os, json, asyncio, uuid as uuid_lib
from typing import Optional, List, Dict, Any

from .base_agent import BaseAgent
from .content_asset_store import ContentAssetStore, ContentAssetData

# ---------------------------------------------------------------------------
# Organic vs Acquisition brand voice presets
# ---------------------------------------------------------------------------
ORGANIC_VOICE = """
Tone: Authentic, relatable, raw. Like a real person sharing their genuine skincare experience.
Feel: Phone-filmed, bathroom mirror, "I just discovered this" energy.
Language:
- First person ("I've been using...", "my skin has never...", "ok but this...")
- Conversational, slightly informal, like talking to a friend
- Real reactions ("I was skeptical but...", "not gonna lie...", "y'all...")
- Imperfect/natural (don't over-polish, keep it real)
- Show real skin texture, don't airbrush
- Emojis: natural placement, 1-3 max
- NO corporate/marketing speak, NO "game-changer", "holy grail"
- Hashtags: mix brand + trending (#MiraiSkin #KBeauty #skincareroutine #glowup)
"""

ACQUISITION_VOICE = """
Tone: Confident, benefit-driven, conversion-focused. Like a premium beauty brand ad.
Feel: Polished production, aspirational, clean aesthetic.
Language:
- Lead with the key benefit or pain point
- Problem → agitate → solve structure
- Strong but not aggressive CTA ("Shop now", "Discover your glow", "Try it risk-free")
- Social proof when possible ("10K+ reviews", "Best-seller")
- Concise, punchy headlines (6-10 words max)
- Professional but warm, not clinical
- Focus on transformation and results
- Emojis: minimal or none
"""

# ---------------------------------------------------------------------------
# UGC-style video concepts (organic / authentic feel)
# ---------------------------------------------------------------------------
UGC_VIDEO_CONCEPTS: Dict[str, Dict[str, Any]] = {
    "real_reaction": {
        "title": "Real First Impression",
        "frames": [
            "POV: holding product at eye level, casual bathroom/bedroom. Phone selfie angle. Natural lighting.",
            "Opening product, genuine curious expression. Slightly shaky handheld feel.",
            "First application — real texture on real skin, no filters. Honest reaction.",
            "10 seconds later — touching face, checking mirror. Authentic surprise or satisfaction.",
        ],
        "mood": "Genuine, unscripted, 'I just tried this' energy.",
        "music_suggestion": "Trending TikTok audio or no music.",
    },
    "get_ready_with_me": {
        "title": "GRWM — Real Routine",
        "frames": [
            "Bathroom mirror POV. Messy counter, real life. Person in robe/t-shirt.",
            "Applying product as part of actual routine. Casual, not posed.",
            "Close-up of skin absorbing product. Natural phone camera quality.",
            "Final look — dewy, real skin. No filter reveal.",
        ],
        "mood": "Relatable, everyday, 'this is actually what I use'.",
        "music_suggestion": "Chill lo-fi or trending audio.",
    },
    "honest_review": {
        "title": "Honest Mini Review",
        "frames": [
            "Talking to camera, casual setting. 'Ok so I've been using this for 2 weeks...'",
            "Showing product packaging, flipping it to show ingredients.",
            "Close-up skin texture — showing real results, not studio-lit.",
        ],
        "mood": "Trustworthy, conversational, no BS.",
        "music_suggestion": "Soft background or none.",
    },
    "skincare_check": {
        "title": "Skin Check-In",
        "frames": [
            "Phone camera selfie, natural light from window. No makeup.",
            "Holding product next to face, casual recommendation pose.",
            "Quick before/after swipe — same angle, different day. Real skin.",
        ],
        "mood": "Casual, 'just checking in with my skin' vibe.",
        "music_suggestion": "Trending sound or ASMR-style.",
    },
}

# ---------------------------------------------------------------------------
# K-Beauty video concept templates — polished / cinematic (for acquisition)
# ---------------------------------------------------------------------------
VIDEO_CONCEPT_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "morning_routine": {
        "title": "Morning Glow Routine",
        "frames": [
            "Golden morning light on a clean vanity, featured product center-frame, dewdrops on mirror.",
            "Close-up: hands dispensing product onto fingertips, natural light catching translucence.",
            "Person patting product into cheeks and forehead, eyes closed, real skin texture visible.",
            "Pull-back reveal: fresh dewy glowing skin, soft smile, product bottle in background.",
        ],
        "mood": "Fresh, optimistic, calm energy.",
        "music_suggestion": "Soft lo-fi or acoustic guitar.",
    },
    "texture_closeup": {
        "title": "Texture Reveal",
        "frames": [
            "Generous dollop on glass or fingertip at near-macro distance, ring-light reflection.",
            "Finger slowly swipes through product in slow-motion — stretchy, bouncy, silky consistency.",
            "Product smoothed across skin, melting from visible layer to absorbed invisible finish.",
            "Skin after absorption — luminous glow, focus racks to product bottle behind.",
        ],
        "mood": "Satisfying, sensory, mesmerising. ASMR energy.",
        "music_suggestion": "Minimal ambient tones, water sounds.",
    },
    "before_after": {
        "title": "Transformation Story",
        "frames": [
            "Close-up skin concern: dryness, dullness, uneven texture. Muted, desaturated grading.",
            "Product bottle enters frame, clean pastel background. Hands apply with circular motions.",
            "Same angle: skin now smooth, hydrated, luminous. Warm golden grading. Dramatic contrast.",
        ],
        "mood": "Empowering, hopeful, dramatic contrast.",
        "music_suggestion": "Building instrumental — soft start, confident finish.",
    },
    "unboxing": {
        "title": "K-Beauty Unboxing Moment",
        "frames": [
            "Sealed package on clean surface, hands opening it. Overhead camera, soft diffused light.",
            "Product emerges from tissue paper, held to camera. Packaging and brand clearly visible.",
            "First swatch dispensed onto finger or wrist, camera captures genuine reaction expression.",
        ],
        "mood": "Excitement, anticipation, tactile pleasure.",
        "music_suggestion": "Playful percussion, gentle chimes.",
    },
    "ingredient_spotlight": {
        "title": "Star Ingredient Deep Dive",
        "frames": [
            "Hero ingredient in raw form — snail on leaf, centella plant, rice grains — botanical light.",
            "Slow dissolve from raw ingredient to product formulation close-up; light refracts through serum.",
            "Applied to glowing skin, camera pulls back showing bottle beside the natural ingredient.",
        ],
        "mood": "Educational, reverent, nature-meets-science.",
        "music_suggestion": "Organic ambient → clean electronic.",
    },
    "evening_wind_down": {
        "title": "Evening Self-Care Ritual",
        "frames": [
            "Dimly lit vanity, candlelight, product among soft towels and candle. Cozy atmosphere.",
            "Featured product applied as final step — slow patting, eyes closed in contentment.",
            "Person touches cheek, smiles softly, hydrated calm skin. Camera widens to serene scene.",
        ],
        "mood": "Peaceful, intimate, luxurious self-care.",
        "music_suggestion": "Warm piano or soft strings, slow tempo.",
    },
}

# ---------------------------------------------------------------------------
# Lazy service loaders (parent directory)
# ---------------------------------------------------------------------------
_sma_instance = None
_blog_gen_instance = None
_seo_instance = None


def _ensure_parent_on_path():
    import sys
    parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if parent not in sys.path:
        sys.path.insert(0, parent)


def _get_social_media_agent():
    global _sma_instance
    if _sma_instance is None:
        _ensure_parent_on_path()
        from social_media_service import SocialMediaAgent
        _sma_instance = SocialMediaAgent()
    return _sma_instance


def _get_blog_generator():
    global _blog_gen_instance
    if _blog_gen_instance is None:
        _ensure_parent_on_path()
        from blog_service import BlogGenerator
        _blog_gen_instance = BlogGenerator()
    return _blog_gen_instance


def _get_seo_agent():
    global _seo_instance
    if _seo_instance is None:
        _ensure_parent_on_path()
        from blog_service import SEOAgent
        _seo_instance = SEOAgent()
    return _seo_instance


def _get_brand_voice() -> str:
    _ensure_parent_on_path()
    from social_media_service import MIRAI_BRAND_VOICE
    return MIRAI_BRAND_VOICE


# ---------------------------------------------------------------------------
# Content Agent
# ---------------------------------------------------------------------------
class ContentAgent(BaseAgent):
    """Agent 2 — Content creation hub.  Produces reusable assets (images,
    videos, text) deployable across organic social, paid ads, and blog."""

    agent_name = "content"

    def __init__(self):
        super().__init__()
        self.asset_store = ContentAssetStore()
        for name in ("create_social_asset", "create_ad_creative", "create_blog_article",
                      "create_multi_format_asset", "create_enhanced_video", "analyze_content_gaps"):
            self.register_handler(name, getattr(self, name))

    def get_supported_tasks(self) -> List[str]:
        return list(self._task_handlers.keys())

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _uid() -> str:
        return str(uuid_lib.uuid4())[:12]

    async def _caption_variants(self, concept: str, product: str,
                                pillar: str, channels: List[str],
                                content_intent: str = "organic") -> Dict[str, str]:
        """Single AI call → channel-specific text variants.
        content_intent: 'organic' (authentic/UGC) or 'acquisition' (polished/CTA)."""
        voice = ORGANIC_VOICE if content_intent == "organic" else ACQUISITION_VOICE
        flds: List[str] = []
        if "instagram" in channels:
            if content_intent == "organic":
                flds.append('"instagram_caption":"IG caption 100-180w, first-person, authentic, hashtags at end, like talking to a friend"')
            else:
                flds.append('"instagram_caption":"IG caption 150-220w, benefit-driven, professional, hashtags at end"')
        if "tiktok" in channels:
            if content_intent == "organic":
                flds.append('"tiktok_caption":"TikTok 20-50w, casual hook first, relatable, trending hashtags"')
            else:
                flds.append('"tiktok_caption":"TikTok 30-60w, punchy hook, benefit-first, trending hashtags"')
        if "ad" in channels:
            flds.append('"ad_headline":"6-10w benefit-driven headline"')
            flds.append('"ad_primary_text":"40-80w problem-agitate-solve, CTA at end"')
        if "blog" in channels:
            flds.append('"blog_intro":"60-100w SEO intro mentioning product"')

        prompt = (
            f"Create channel text for K-Beauty asset.\nCONCEPT: {concept}\n"
            f"PRODUCT: {product}\nPILLAR: {pillar}\n"
            f"\nCONTENT INTENT: {content_intent.upper()}\n\n"
            f"VOICE & TONE GUIDE:\n{voice}\n\n"
            f"Return JSON:\n{{{', '.join(flds)},\n"
            f'"headline":"8-12w universal","body_copy":"50-80w universal",'
            f'"cta_text":"soft CTA 4-8w","hashtags":["#MiraiSkin","#KBeauty","#KoreanSkincare","..."]}}'
        )
        sys_prompt = ("Authentic K-Beauty content creator. Write like a real person, not a brand. Valid JSON only."
                      if content_intent == "organic"
                      else "Senior K-Beauty performance copywriter. Valid JSON only.")
        raw = await self.call_ai_text(prompt=prompt,
            system_prompt=sys_prompt,
            temperature=0.75, json_mode=True)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"headline": concept, "body_copy": "", "hashtags": ["#MiraiSkin", "#KBeauty"]}

    async def _build_asset(self, title: str, concept: str, product: str,
                           pillar: str, category: str, pids: List[str],
                           txt: Dict, *, img=None, vid=None, gp=None,
                           content_intent: str = "") -> ContentAssetData:
        """Assemble, persist, return a ContentAssetData."""
        a = ContentAssetData(
            uuid=self._uid(), title=title, content_pillar=pillar,
            content_category=category, product_ids=pids, brand="Mirai Skin",
            content_intent=content_intent,
            headline=txt.get("headline", ""), body_copy=txt.get("body_copy", ""),
            cta_text=txt.get("cta_text", ""), hashtags=txt.get("hashtags", []),
            seo_keywords=txt.get("seo_keywords", []),
            instagram_caption=txt.get("instagram_caption", ""),
            tiktok_caption=txt.get("tiktok_caption", ""),
            ad_headline=txt.get("ad_headline", ""),
            ad_primary_text=txt.get("ad_primary_text", ""),
            blog_intro=txt.get("blog_intro", ""),
            visual_direction=txt.get("visual_direction", concept),
            video_direction=txt.get("video_direction", ""),
            ai_model_text="gemini", generation_params=gp or {},
            status="draft", created_by_agent=self.agent_name,
        )
        if img and img[0]:
            a.primary_image_data = img[0]
            a.primary_image_thumbnail = img[1]
            a.primary_image_format = img[2] or "png"
            a.ai_model_image = img[3] if len(img) > 3 else "gemini"
        if vid and vid[0]:
            a.video_data = vid[0]
            a.video_thumbnail = vid[1] or ""
            a.video_format = vid[2] or "mp4"
            a.ai_model_video = "veo2"
            a.video_duration_seconds = 8
        await self.asset_store.save_asset(a)
        return a

    def _pick_concept(self, key: Optional[str], product: str,
                      content_intent: str = "organic") -> Dict[str, Any]:
        """Select video concept template by key, product heuristic, and intent.
        Organic → UGC-style templates. Acquisition → polished cinematic templates."""
        # Check explicit key in both pools
        if key:
            if key in UGC_VIDEO_CONCEPTS:
                return UGC_VIDEO_CONCEPTS[key]
            if key in VIDEO_CONCEPT_TEMPLATES:
                return VIDEO_CONCEPT_TEMPLATES[key]

        # Organic → pick from UGC pool
        if content_intent == "organic":
            import random as _rnd
            return _rnd.choice(list(UGC_VIDEO_CONCEPTS.values()))

        # Acquisition → pick from polished pool by product heuristic
        lo = (product or "").lower()
        if any(k in lo for k in ("cleanser", "cleansing", "oil", "balm")):
            return VIDEO_CONCEPT_TEMPLATES["evening_wind_down"]
        if any(k in lo for k in ("serum", "essence", "ampoule")):
            return VIDEO_CONCEPT_TEMPLATES["texture_closeup"]
        if any(k in lo for k in ("snail", "centella", "mugwort", "niacinamide", "rice")):
            return VIDEO_CONCEPT_TEMPLATES["ingredient_spotlight"]
        return VIDEO_CONCEPT_TEMPLATES["morning_routine"]

    def _veo2_prompt(self, tmpl: Dict[str, Any], product: str,
                     content_intent: str = "organic") -> str:
        """Frame-by-frame Veo 2 prompt from a concept template.
        Organic → UGC phone-filmed style. Acquisition → polished cinematic."""
        frames = " ".join(f"[Frame {i+1}] {f}" for i, f in enumerate(tmpl["frames"]))

        if content_intent == "organic":
            return (
                f"Vertical video shot on phone — UGC-style, raw, authentic. "
                f"NOT cinematic. NOT stock footage. K-Beauty content for Mirai Skin. "
                f"Concept: {tmpl['title']}. Product: \"{product}\". Mood: {tmpl['mood']}"
                f"\n\nFRAMES:\n{frames}"
                f"\n\nSTYLE: Phone camera quality, slightly handheld, natural window light. "
                f"Real skin texture visible, no airbrushing. Casual bedroom/bathroom setting. "
                f"Like a real person filming their skincare routine for TikTok or IG Reels."
                f"\n\nNO text, captions, titles, labels, watermarks, or overlays."
            )
        else:
            return (
                f"Cinematic vertical video for Instagram Reels — K-Beauty content for Mirai Skin. "
                f"Concept: {tmpl['title']}. Product: \"{product}\". Mood: {tmpl['mood']}"
                f"\n\nFRAMES:\n{frames}"
                f"\n\nSTYLE: Natural soft lighting, warm tones, real skin. Smooth slow-motion. "
                f"Aspirational beauty aesthetic, polished production quality."
                f"\n\nNO text, captions, titles, labels, watermarks, or overlays."
            )

    # ================================================== TASK HANDLERS

    async def create_social_asset(self, params: dict) -> dict:
        """Image + caption for organic social.
        Params: concept, product_name, product_ids, content_pillar,
                post_type, image_engine, product_image_url, content_intent."""
        concept  = params.get("concept", "K-Beauty skincare routine")
        product  = params.get("product_name", "")
        pids     = params.get("product_ids", [])
        pillar   = params.get("content_pillar", "lifestyle")
        ptype    = params.get("post_type", "photo")
        engine   = params.get("image_engine", "gemini")
        ref_url  = params.get("product_image_url", "")
        intent   = params.get("content_intent", "organic")

        await self.log_decision("create_social_asset",
            {"concept": concept, "product": product, "post_type": ptype, "content_intent": intent},
            {"action": "generate_image_and_caption"},
            f"Social asset ({intent}) for '{concept}' via {engine}.", 0.85, False)

        txt = await self._caption_variants(concept, product, pillar, ["instagram", "tiktok"],
                                           content_intent=intent)
        sma = _get_social_media_agent()
        img = await sma._generate_image(
            visual_direction=txt.get("visual_direction", concept), post_type=ptype,
            engine=engine, caption=txt.get("instagram_caption", ""),
            product_image_url=ref_url, product_name=product)

        asset = await self._build_asset(
            txt.get("headline", concept[:60]), concept, product, pillar,
            "social_post", pids, txt, img=img,
            gp={"post_type": ptype, "image_engine": engine},
            content_intent=intent)
        return {"asset_uuid": asset.uuid, "title": asset.title,
                "content_intent": intent,
                "has_image": asset.primary_image_data is not None,
                "image_format": asset.primary_image_format,
                "instagram_caption_preview": (asset.instagram_caption or "")[:200],
                "tiktok_caption_preview": (asset.tiktok_caption or "")[:120],
                "hashtags": asset.hashtags, "status": asset.status}

    async def create_ad_creative(self, params: dict) -> dict:
        """Ad-optimised asset (punchier headline, CTA).
        Params: concept, product_name, product_ids, content_pillar,
                target_audience, ad_objective, image_engine, product_image_url, content_intent."""
        concept   = params.get("concept", "K-Beauty skincare solution")
        product   = params.get("product_name", "")
        pids      = params.get("product_ids", [])
        pillar    = params.get("content_pillar", "promotion")
        audience  = params.get("target_audience", "Women 25-40 interested in Korean skincare")
        objective = params.get("ad_objective", "conversions")
        engine    = params.get("image_engine", "gemini")
        ref_url   = params.get("product_image_url", "")
        intent    = params.get("content_intent", "acquisition")

        await self.log_decision("create_ad_creative",
            {"concept": concept, "objective": objective, "content_intent": intent},
            {"action": "generate_ad_asset"},
            f"Ad ({intent}) for '{concept}', audience='{audience}', obj='{objective}'.", 0.8, True)

        voice = ACQUISITION_VOICE if intent == "acquisition" else ORGANIC_VOICE
        prompt = (
            f"Create Meta/IG ad copy.\nCONCEPT: {concept}\nPRODUCT: {product}\n"
            f"AUDIENCE: {audience}\nOBJECTIVE: {objective}\n"
            f"\nCONTENT INTENT: {intent.upper()}\n\n"
            f"VOICE & TONE GUIDE:\n{voice}\n\n"
            "RULES: headline 6-10w benefit-first; primary_text 40-80w problem-agitate-solve; "
            "CTA direct but not aggressive.\n\n"
            "Return JSON: {ad_headline, ad_primary_text, cta_text, headline, body_copy, "
            "visual_direction, hashtags[], instagram_caption, target_hook}"
        )
        raw = await self.call_ai_text(prompt=prompt,
            system_prompt="DTC beauty performance copywriter. Valid JSON only.",
            temperature=0.7, json_mode=True)
        try:
            txt = json.loads(raw)
        except json.JSONDecodeError:
            txt = {"ad_headline": concept[:40], "ad_primary_text": concept}

        sma = _get_social_media_agent()
        img = await sma._generate_image(
            visual_direction=txt.get("visual_direction", concept), post_type="photo",
            engine=engine, caption="", product_image_url=ref_url, product_name=product)

        asset = await self._build_asset(
            f"Ad: {txt.get('ad_headline', concept[:50])}", concept, product, pillar,
            "ad_creative", pids, txt, img=img,
            gp={"ad_objective": objective, "target_audience": audience, "image_engine": engine},
            content_intent=intent)
        return {"asset_uuid": asset.uuid, "ad_headline": asset.ad_headline,
                "content_intent": intent,
                "ad_primary_text_preview": (asset.ad_primary_text or "")[:200],
                "cta_text": asset.cta_text, "has_image": asset.primary_image_data is not None,
                "target_hook": txt.get("target_hook", ""),
                "ad_objective": objective, "status": asset.status}

    async def create_blog_article(self, params: dict) -> dict:
        """Blog article via BlogGenerator.
        Params: category, topic, keywords[], word_count, product_name, product_ids."""
        category  = params.get("category", "lifestyle")
        topic     = params.get("topic", "")
        keywords  = params.get("keywords", ["K-beauty", "Korean skincare"])
        wc        = params.get("word_count", 1000)
        product   = params.get("product_name", "")
        pids      = params.get("product_ids", [])
        if not topic:
            return {"error": "topic is required"}

        await self.log_decision("create_blog_article",
            {"category": category, "topic": topic},
            {"action": "generate_via_blog_generator"},
            f"Blog in '{category}' about '{topic}'.", 0.9, True)

        draft = _get_blog_generator().generate_article(
            category=category, topic=topic, keywords=keywords,
            word_count=wc, user_email="content_agent")
        txt = {"headline": draft.title, "body_copy": draft.excerpt,
               "blog_intro": draft.excerpt, "seo_keywords": keywords,
               "hashtags": [f"#{t.replace(' ', '')}" for t in (draft.suggested_tags or [])]}

        asset = await self._build_asset(
            draft.title, topic, product, "education", "blog_article", pids, txt,
            gp={"blog_draft_id": draft.id, "category": category, "word_count": draft.word_count})
        await self.asset_store.mark_used(asset.uuid, "blog", draft.id)
        return {"asset_uuid": asset.uuid, "blog_draft_id": draft.id,
                "title": draft.title, "category": category,
                "word_count": draft.word_count, "meta_description": draft.meta_description,
                "excerpt_preview": (draft.excerpt or "")[:200],
                "suggested_tags": draft.suggested_tags, "status": asset.status}

    async def create_multi_format_asset(self, params: dict) -> dict:
        """ONE concept → all formats (image, video, IG/TikTok/ad/blog).
        Generates BOTH organic and acquisition text variants from a single asset.
        Params: concept, product_name, product_ids, content_pillar,
                video_concept_key, image_engine, product_image_url, skip_video, content_intent."""
        concept  = params.get("concept", "K-Beauty skincare essential")
        product  = params.get("product_name", "")
        pids     = params.get("product_ids", [])
        pillar   = params.get("content_pillar", "lifestyle")
        vkey     = params.get("video_concept_key")
        engine   = params.get("image_engine", "gemini")
        ref_url  = params.get("product_image_url", "")
        no_vid   = params.get("skip_video", False)
        intent   = params.get("content_intent", "organic")

        await self.log_decision("create_multi_format_asset",
            {"concept": concept, "product": product, "content_intent": intent},
            {"action": "generate_all_formats"},
            f"Multi-format ({intent}) for '{concept}'. Video={'no' if no_vid else 'yes'}.", 0.85, True)

        # Generate BOTH organic and acquisition text variants in parallel
        organic_txt_coro = self._caption_variants(concept, product, pillar,
                                                   ["instagram", "tiktok"], content_intent="organic")
        acquisition_txt_coro = self._caption_variants(concept, product, pillar,
                                                       ["ad", "blog"], content_intent="acquisition")
        organic_txt, acquisition_txt = await asyncio.gather(organic_txt_coro, acquisition_txt_coro)

        # Merge: organic captions + acquisition ad/blog copy
        txt = {**organic_txt, **acquisition_txt}
        # Keep the organic headline as primary for the asset
        txt["headline"] = organic_txt.get("headline", concept[:60])

        sma = _get_social_media_agent()
        vis = txt.get("visual_direction", concept)

        img_coro = sma._generate_image(visual_direction=vis, post_type="photo",
            engine=engine, caption=txt.get("instagram_caption", ""),
            product_image_url=ref_url, product_name=product)

        vid_result = None
        if not no_vid:
            tmpl = self._pick_concept(vkey, product, content_intent=intent)
            vp = self._veo2_prompt(tmpl, product, content_intent=intent)
            txt["video_direction"] = vp
            vid_coro = sma._generate_video(visual_direction=vp,
                caption=txt.get("instagram_caption", ""), product_name=product)
            img_result, vid_result = await asyncio.gather(img_coro, vid_coro)
        else:
            img_result = await img_coro

        asset = await self._build_asset(
            txt.get("headline", concept[:60]), concept, product, pillar,
            "multi_format", pids, txt, img=img_result, vid=vid_result,
            gp={"image_engine": engine, "video_concept": vkey or "auto",
                "skip_video": no_vid, "content_intent": intent},
            content_intent=intent)
        return {"asset_uuid": asset.uuid, "title": asset.title,
                "content_intent": intent,
                "formats_generated": {
                    "image": asset.primary_image_data is not None,
                    "video": asset.video_data is not None,
                    "instagram_caption": bool(asset.instagram_caption),
                    "tiktok_caption": bool(asset.tiktok_caption),
                    "ad_headline": bool(asset.ad_headline),
                    "blog_intro": bool(asset.blog_intro),
                },
                "headline": asset.headline, "ad_headline": asset.ad_headline,
                "cta_text": asset.cta_text, "hashtags": asset.hashtags,
                "video_duration_seconds": asset.video_duration_seconds,
                "status": asset.status}

    async def create_enhanced_video(self, params: dict) -> dict:
        """Multi-take Veo 2 video with frame-by-frame prompts.
        Generates num_takes variants, selects best by size heuristic.
        Params: concept, product_name, product_ids, content_pillar,
                video_concept_key, num_takes (default 2, max 3), content_intent."""
        concept  = params.get("concept", "K-Beauty skincare video")
        product  = params.get("product_name", "")
        pids     = params.get("product_ids", [])
        pillar   = params.get("content_pillar", "lifestyle")
        vkey     = params.get("video_concept_key")
        takes    = min(params.get("num_takes", 2), 3)
        intent   = params.get("content_intent", "organic")

        tmpl = self._pick_concept(vkey, product, content_intent=intent)
        await self.log_decision("create_enhanced_video",
            {"concept": concept, "template": tmpl["title"], "takes": takes, "content_intent": intent},
            {"action": "multi_take_video"},
            f"{takes} takes ({intent}) via '{tmpl['title']}', best by size.", 0.75, False)

        base = self._veo2_prompt(tmpl, product, content_intent=intent)
        txt = await self._caption_variants(concept, product, pillar, ["instagram", "tiktok"],
                                           content_intent=intent)
        txt["video_direction"] = base

        # Slight prompt variations for diversity
        suffixes = [
            " Warm golden tones, intimate close-ups.",
            " Cooler blue-white tones, wider establishing shots.",
            " Extreme detail on hands and product interaction.",
        ]
        prompts = [base] + [base + suffixes[i % len(suffixes)] for i in range(1, takes)]

        sma = _get_social_media_agent()
        results = await asyncio.gather(
            *[sma._generate_video(visual_direction=p,
                caption=txt.get("instagram_caption", ""), product_name=product)
              for p in prompts],
            return_exceptions=True)

        best, best_sz, ok = None, 0, 0
        for r in results:
            if isinstance(r, Exception) or not r or not r[0]:
                continue
            ok += 1
            sz = len(r[0])
            if sz > best_sz:
                best_sz, best = sz, r

        if not best:
            return {"error": "All video takes failed.", "takes_attempted": takes, "takes_succeeded": 0}

        # Still image as thumbnail / fallback
        img = await sma._generate_image(visual_direction=concept, post_type="reel",
            engine="gemini", caption=txt.get("instagram_caption", ""), product_name=product)

        asset = await self._build_asset(
            f"Video: {txt.get('headline', concept[:50])}", concept, product,
            pillar, "enhanced_video", pids, txt, img=img, vid=best,
            gp={"video_concept": tmpl["title"], "num_takes": takes,
                "takes_succeeded": ok, "best_take_bytes": best_sz,
                "mood": tmpl["mood"], "music_suggestion": tmpl["music_suggestion"]},
            content_intent=intent)
        return {"asset_uuid": asset.uuid, "title": asset.title,
                "video_concept": tmpl["title"],
                "has_video": True, "has_thumbnail": asset.primary_image_data is not None,
                "video_duration_seconds": 8,
                "takes_attempted": takes, "takes_succeeded": ok,
                "mood": tmpl["mood"], "music_suggestion": tmpl["music_suggestion"],
                "instagram_caption_preview": (asset.instagram_caption or "")[:200],
                "status": asset.status}

    async def analyze_content_gaps(self, params: dict) -> dict:
        """Gap analysis via SEOAgent, optional smart suggestions.
        Params: existing_articles[], generate_suggestions (bool), suggestion_count."""
        existing   = params.get("existing_articles")
        do_sug     = params.get("generate_suggestions", True)
        count      = params.get("suggestion_count", 5)

        await self.log_decision("analyze_content_gaps",
            {"suggestions": do_sug, "count": count},
            {"action": "run_gap_analysis"},
            "Content gap analysis to find underserved topics.", 0.9, False)

        seo = _get_seo_agent()
        gaps = seo.analyze_content_gaps(existing_articles=existing)

        result: Dict[str, Any] = {
            "gaps": gaps,
            "categories_needing_content": gaps.get("categories_needing_content", []),
            "trending_ingredients_not_covered": [
                i.get("name", "") for i in gaps.get("trending_ingredients_not_covered", [])],
            "seasonal_opportunities": gaps.get("seasonal_opportunities", []),
        }

        if do_sug and seo.client:
            try:
                sugs = seo.generate_smart_suggestions(count=count, force_refresh=True)
                result["suggestions"] = [
                    {"title": s.title, "category": s.category, "topic": s.topic,
                     "keywords": s.keywords, "reason": s.reason, "priority": s.priority,
                     "estimated_traffic": s.estimated_traffic}
                    for s in sugs]
            except Exception as exc:
                result["suggestions_error"] = str(exc)
                result["suggestions"] = []

        # Auto-queue tasks for high-priority gaps
        created = []
        for s in result.get("suggestions", [])[:2]:
            if s.get("priority") == "high":
                tid = await self.create_task(
                    target_agent="content", task_type="create_blog_article",
                    params={"category": s["category"], "topic": s["topic"],
                            "keywords": s.get("keywords", [])},
                    priority="normal")
                created.append({"task_id": tid, "topic": s["topic"]})
        result["follow_up_tasks_created"] = created
        return result
