# Mirai Skin Meta Ads Campaign Strategy

## Goal
- **Target CPA:** €25-35 (acceptable range)
- **Max CPA:** €40 (budget limit for early stage)
- **Conversion Rate:** 1-2% click-to-purchase
- **Daily Budget:** €20-50 (scale as we find winners)

## Funnel Math
```
At €35 CPA with 1.5% conversion:
- Need ~67 clicks per purchase
- Target CPC: €0.50-0.60
- Target CPM: €15-20 (watch for high CPM = expensive audience)

Early Stage Reality Check:
- CPM can be €20-30 in competitive beauty space
- Focus on CTR first, CPA will improve with pixel learning
```

## 3-Phase Strategy

### Phase 1: Lead Generation (Weeks 1-2)
**Objective:** LEADS (Quiz Completes)
- Build pixel data
- Find winning ad creatives
- Identify best audiences
- **Target CPA:** €3-5 per quiz complete

### Phase 2: Retargeting (Week 3+)
**Objective:** CONVERSIONS (Purchases)
- Retarget quiz completers
- Push for Add to Cart + Purchase
- **Expected conversion:** 10-15% of quiz completers

### Phase 3: Scale (Week 4+)
**Objective:** CONVERSIONS with Lookalikes
- Build lookalike audiences from purchasers
- Scale winning ads
- Expand targeting

## Campaign Structure

```
Campaign: Mirai Skin - Korean Skincare Quiz
├── Ad Set 1: US Women 25-45 - K-Beauty Interest
│   ├── Ad 1: Scan Results (ad_01)
│   ├── Ad 2: Discover Routine (ad_02)
│   ├── Ad 3: Made Personal (ad_03)
│   ├── Ad 4: Side Panel (ad_04)
│   └── Ad 5: Morning Ritual (ad_05)
│
└── Ad Set 2: US Women 25-45 - Skincare Broad
    └── (Same 5 ads)
```

## Target Audience

### Demographics
- **Gender:** Female
- **Age:** 25-55
- **Location:** United States

### Interests (Phase 1)
- K-beauty / Korean skincare
- Skincare routine
- Anti-aging skincare
- Natural beauty
- Glossier, Sephora, Ulta Beauty

### Behaviors
- Online shoppers
- Engaged shoppers
- Beauty enthusiasts

## Ad Copy Templates

### PROSPECTING (Cold Traffic)

**Primary Text:**
```
Your perfect Korean skincare routine is just a selfie away ✨

Take our free AI skin analysis:
→ Snap a quick selfie
→ Get your skin scores
→ Discover your personalized routine

No guesswork. Just results.
```

**Headline:** `Find Your Korean Skincare Routine`
**Description:** `Free AI Skin Analysis - Takes 60 seconds`
**CTA:** `Learn More`

---

### RETARGETING - Quiz Completers (saw results, didn't buy)

**Primary Text Option 1:**
```
Your personalized Korean skincare routine is ready ✨

Based on your skin analysis, we've curated the perfect products for your:
• Hydration needs
• Skin concerns
• Daily routine

Your results are waiting. Ready to glow?
```

**Primary Text Option 2:**
```
Remember your skin analysis? Your routine is still waiting 💫

We matched you with Korean skincare products specifically for YOUR skin type.

See your personalized recommendations →
```

**Primary Text Option 3:**
```
Good news: Your AI skin analysis found your perfect matches 🎯

We analyzed thousands of K-beauty products to find the ones that work for your specific skin concerns.

Your customized routine is one click away.
```

**Headlines for Retargeting:**
- `Your Personalized Routine is Ready`
- `Your Skin Analysis Results`
- `Curated Just For Your Skin`
- `Your K-Beauty Matches Await`

**Descriptions:**
- `See Your Personalized Products`
- `Based on Your Skin Analysis`
- `Matched to Your Skin Type`

---

### RETARGETING - Add to Cart Abandoners

**Primary Text:**
```
Still thinking about it? 🤔

Your Korean skincare picks are still in your cart, waiting to transform your routine.

Complete your order and start your glow-up journey →
```

**Headline:** `Complete Your Order`
**Description:** `Your cart is waiting`

---

### RETARGETING - Website Visitors (browsed but no quiz)

**Primary Text:**
```
Curious about Korean skincare but not sure where to start?

Take our 60-second AI skin analysis and we'll match you with products that actually work for YOUR skin.

No commitment. Just answers.
```

**Headline:** `Not Sure What Your Skin Needs?`
**Description:** `Free AI Skin Analysis - 60 Seconds`

---

### ❌ AVOID These Phrases (not accurate for our funnel):
- "Pick up where you left off" (implies saved progress)
- "Continue your journey" (too vague)
- "You forgot something" (aggressive)
- "Don't miss out" (overused)

## KPIs & Decision Rules

| Metric | Good | Acceptable | Review Needed | Pause |
|--------|------|------------|---------------|-------|
| CTR | >2% | 1-2% | 0.6-1% | <0.6% |
| CPC | <€0.40 | €0.40-0.60 | €0.60-0.80 | >€0.80 |
| CPM | <€15 | €15-20 | €20-30 | >€30 |
| CPL (Quiz) | <€5 | €5-8 | €8-12 | >€12 |
| CPA (Purchase) | <€25 | €25-35 | €35-40 | >€40 |
| ROAS | >2.5x | 1.5-2.5x | 1-1.5x | <1x |

### Decision Timeline
- **Days 1-3:** PROTECTED - No pause decisions, gather data
- **Days 3-5:** LEARNING - Monitor trends, minor adjustments only
- **Days 5-10:** LEARNING - Can pause clear losers (CTR < 0.6%)
- **Day 10+:** MATURE - Full optimization enabled

## Budget Allocation

### Phase 1 (€20/day)
- Ad Set 1 (K-Beauty): €12/day
- Ad Set 2 (Broad): €8/day

### After Learning Phase
- Scale winners to 70% of budget
- Keep 30% for testing new creatives

## Pixel Events to Track
- PageView
- StartAnalysis (Quiz Start)
- CompleteAnalysis (Quiz Complete) ← Primary conversion
- AddToCart
- InitiateCheckout
- Purchase ← Ultimate goal
