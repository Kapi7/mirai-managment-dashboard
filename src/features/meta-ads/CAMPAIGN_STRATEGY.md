# Mirai Skin Meta Ads Campaign Strategy

## Goal
- **Target CPA:** €18.50 (~$20) per purchase
- **Conversion Rate:** 2% click-to-purchase
- **Daily Budget:** €20

## Funnel Math
```
Target: €18.50 CPA
At 2% conversion: Need 50 clicks per purchase
Target CPC: €18.50 / 50 = €0.37
At 2% CTR: Target CPM = €18.50 (€0.37 × 50)
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

### Primary Text
```
Your perfect Korean skincare routine is just a selfie away ✨

Take our free AI skin analysis:
→ Snap a quick selfie
→ Get your skin scores
→ Discover your personalized routine

No guesswork. Just results.
```

### Headline
```
Find Your Korean Skincare Routine
```

### Description
```
Free AI Skin Analysis - Takes 60 seconds
```

### CTA
```
Learn More → miraiskin.co/quiz
```

## KPIs & Decision Rules

| Metric | Good | Acceptable | Action Needed |
|--------|------|------------|---------------|
| CTR | >2% | 1-2% | <1% pause |
| CPC | <€0.30 | €0.30-0.50 | >€0.50 review |
| CPL (Quiz) | <€3 | €3-5 | >€5 pause |
| CPA (Purchase) | <€15 | €15-20 | >€20 pause |

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
