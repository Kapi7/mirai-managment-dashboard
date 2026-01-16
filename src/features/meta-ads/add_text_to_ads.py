#!/usr/bin/env python3
"""
Add campaign text to selected photos
Matching Mirai Skin website design
Font: Clean sans-serif, Colors: #000000, #FFFFFF, #D63A2F (accent)
"""

from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

INPUT_DIR = Path(__file__).parent / "campaign-assets" / "originals"
OUTPUT_DIR = Path(__file__).parent / "campaign-assets" / "ready"

# Website colors
BLACK = "#000000"
WHITE = "#FFFFFF"
ACCENT_RED = "#D63A2F"
LIGHT_GRAY = "#666666"
WARM_BEIGE = "#F3EEEA"

def get_font(size, bold=False):
    """Get a clean sans-serif font matching website"""
    font_paths = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for path in font_paths:
        try:
            return ImageFont.truetype(path, size)
        except:
            continue
    return ImageFont.load_default()

def create_ad_1_scan_results():
    """Ad with step4_see_scores - shows the scan results"""
    img_path = INPUT_DIR / "step4_see_scores.png"
    img = Image.open(img_path).convert('RGBA')
    width, height = img.size

    # Subtle dark gradient at top
    overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    for i in range(180):
        alpha = int(120 * (1 - i / 180))
        overlay_draw.line([(0, i), (width, i)], fill=(0, 0, 0, alpha))

    # Light gradient at bottom
    for i in range(100):
        alpha = int(100 * (i / 100))
        y = height - 100 + i
        overlay_draw.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))

    img = Image.alpha_composite(img, overlay)
    draw = ImageDraw.Draw(img)

    # Clean typography - larger, bolder
    font_headline = get_font(48, bold=True)
    font_sub = get_font(32)
    font_flow = get_font(28, bold=True)

    # Top headline
    draw.text((40, 35), "Your Korean Skincare", font=font_headline, fill=WHITE)
    draw.text((40, 90), "Routine Starts Here", font=font_sub, fill=WHITE)

    # Bottom flow
    draw.text((40, height - 70), "SELFIE  →  SCAN  →  ROUTINE", font=font_flow, fill=WHITE)

    return img.convert('RGB')

def create_ad_2_discover():
    """Ad with lifestyle_03_ritual_bliss - applying serum"""
    img_path = INPUT_DIR / "lifestyle_03_ritual_bliss.png"
    img = Image.open(img_path).convert('RGBA')
    width, height = img.size

    # Dark gradient at top
    overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    for i in range(250):
        alpha = int(160 * (1 - i / 250))
        overlay_draw.line([(0, i), (width, i)], fill=(0, 0, 0, alpha))

    # Bottom gradient
    for i in range(150):
        alpha = int(140 * (i / 150))
        y = height - 150 + i
        overlay_draw.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))

    img = Image.alpha_composite(img, overlay)
    draw = ImageDraw.Draw(img)

    # Large clear text
    font_small = get_font(36)
    font_large = get_font(64, bold=True)
    font_bottom = get_font(32)

    draw.text((50, 50), "Discover Your", font=font_small, fill=WHITE)
    draw.text((50, 95), "Perfect Korean", font=font_large, fill=WHITE)
    draw.text((50, 170), "Skincare Routine", font=font_large, fill=WHITE)

    # Bottom
    draw.text((50, height - 120), "AI-Powered Skin Analysis", font=font_bottom, fill=WHITE)
    draw.text((50, height - 75), "Personalized Just For You", font=font_bottom, fill=WHITE)

    return img.convert('RGB')

def create_ad_3_personal():
    """Ad with 04_results_discovery - woman with phone"""
    img_path = INPUT_DIR / "04_results_discovery.png"
    img = Image.open(img_path).convert('RGBA')
    width, height = img.size

    # Bottom gradient only - keep image clean
    overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    for i in range(180):
        alpha = int(200 * (i / 180))
        y = height - 180 + i
        overlay_draw.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))

    img = Image.alpha_composite(img, overlay)
    draw = ImageDraw.Draw(img)

    # Bold headline
    font_large = get_font(52, bold=True)
    font_flow = get_font(30)

    draw.text((40, height - 150), "Korean Skincare", font=font_large, fill=WHITE)
    draw.text((40, height - 90), "Made Personal", font=font_large, fill=WHITE)
    draw.text((40, height - 45), "Selfie  •  Scan  •  Your Daily Routine", font=font_flow, fill=WHITE)

    return img.convert('RGB')

def create_ad_4_side():
    """Ad with 03_ai_analysis_glow - face with side panel"""
    img_path = INPUT_DIR / "03_ai_analysis_glow.png"
    img = Image.open(img_path).convert('RGBA')
    width, height = img.size

    # Create wider canvas with beige panel
    new_width = int(width * 1.6)
    new_img = Image.new('RGBA', (new_width, height), (243, 238, 234, 255))
    new_img.paste(img, (0, 0))

    draw = ImageDraw.Draw(new_img)

    # Text on right panel - clean and large
    text_x = width + 40
    font_small = get_font(28)
    font_large = get_font(48, bold=True)
    font_steps = get_font(24)

    # Headline
    center_y = height // 2 - 100
    draw.text((text_x, center_y), "Your", font=font_small, fill=BLACK)
    draw.text((text_x, center_y + 35), "Korean", font=font_large, fill=BLACK)
    draw.text((text_x, center_y + 90), "Skincare", font=font_large, fill=BLACK)
    draw.text((text_x, center_y + 145), "Routine", font=font_large, fill=BLACK)

    # Steps with accent
    steps_y = center_y + 220
    draw.text((text_x, steps_y), "1. Take a selfie", font=font_steps, fill=LIGHT_GRAY)
    draw.text((text_x, steps_y + 35), "2. AI scans your skin", font=font_steps, fill=LIGHT_GRAY)
    draw.text((text_x, steps_y + 70), "3. Get your routine", font=font_steps, fill=ACCENT_RED)

    return new_img.convert('RGB')

def create_ad_5_morning():
    """Ad with 07_morning_ritual"""
    img_path = INPUT_DIR / "07_morning_ritual.png"
    img = Image.open(img_path).convert('RGBA')
    width, height = img.size

    # Top gradient
    overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    for i in range(200):
        alpha = int(150 * (1 - i / 200))
        overlay_draw.line([(0, i), (width, i)], fill=(0, 0, 0, alpha))

    img = Image.alpha_composite(img, overlay)
    draw = ImageDraw.Draw(img)

    # Clear large text
    font_small = get_font(30)
    font_large = get_font(48, bold=True)

    draw.text((35, 35), "Find Your Perfect", font=font_small, fill=WHITE)
    draw.text((35, 75), "Korean Skincare", font=font_large, fill=WHITE)
    draw.text((35, 130), "Routine", font=font_large, fill=WHITE)

    return img.convert('RGB')

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    ads = [
        ("ad_01_scan_results.png", create_ad_1_scan_results),
        ("ad_02_discover_routine.png", create_ad_2_discover),
        ("ad_03_made_personal.png", create_ad_3_personal),
        ("ad_04_side_panel.png", create_ad_4_side),
        ("ad_05_morning.png", create_ad_5_morning),
    ]

    for filename, create_func in ads:
        print(f"Creating {filename}...")
        try:
            img = create_func()
            output_path = OUTPUT_DIR / filename
            img.save(str(output_path), quality=95)
            print(f"  ✓ Saved")
        except Exception as e:
            print(f"  ✗ Error: {e}")

    print(f"\n✅ Done! Ads in: {OUTPUT_DIR}")

if __name__ == "__main__":
    main()
