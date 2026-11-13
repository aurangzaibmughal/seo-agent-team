import re
import sys
from pathlib import Path

# Add backend directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agents.content_agent import extract_brand_from_page, rewrite_natural_title, rewrite_natural_meta

fixture_pages = [
    ("https://www.alghaffar.com.pk/", "Al Ghaffar Travel – Hajj, Umrah & Holiday Tour Packages Karachi", "Al Ghaffar Travel & Tours", "Explore top holiday tour packages and Umrah services."),
    ("https://www.alghaffar.com.pk/about/", "About Us | Al Ghaffar Travel", "About Al Ghaffar", "Learn more about our travel company history and values."),
    ("https://www.alghaffar.com.pk/services/", "Our Services | Al Ghaffar", "Travel & Tour Services", "Comprehensive flight, visa, and hotel reservation solutions."),
    ("https://www.alghaffar.com.pk/trip/", "Holiday Tour Packages | Al Ghaffar", "Curated Holiday Packages", "Explore all worldwide holiday packages and budget tours."),
    ("https://www.alghaffar.com.pk/contact/", "Contact Us | Al Ghaffar", "Get in Touch with Our Team", "Contact our office in Karachi for booking and customer support."),
    ("https://www.alghaffar.com.pk/career/", "Careers & Jobs | Al Ghaffar", "Join Our Travel Team", "Explore career opportunities and job openings at our Karachi office."),
    ("https://www.alghaffar.com.pk/faqs/", "Frequently Asked Questions | Al Ghaffar", "FAQs & Answers", "Find answers to common questions about booking, visas, and refunds."),
    ("https://www.alghaffar.com.pk/destinations/sri-lanka/", "Sri Lanka Tour Packages | Al Ghaffar", "Sri Lanka Vacation Packages", "Discover Sri Lanka holiday itineraries and scenic tours."),
    ("https://www.alghaffar.com.pk/trip/thailand/", "Thailand Holiday Package | Al Ghaffar", "Thailand Tour Packages", "Enjoy Thailand beaches, Bangkok city tours, and family vacations."),
    ("https://www.alghaffar.com.pk/trip/sri-lanka/", "Sri Lanka Travel Deals | Al Ghaffar", "Sri Lanka Tour Offers", "Affordable Sri Lanka holiday deals and sightseeing itineraries."),
    ("https://www.alghaffar.com.pk/destinations/thailand/", "Thailand Travel Guide | Al Ghaffar", "Thailand Guide & Packages", "Complete travel guide for Thailand holiday planning."),
    ("https://www.alghaffar.com.pk/trip/kuala-lumpur/", "Kuala Lumpur Tours | Al Ghaffar", "Kuala Lumpur Packages", "Explore Kuala Lumpur city breaks and Malaysia tour deals."),
    ("https://www.alghaffar.com.pk/destinations/kuala-kumpur/", "Kuala Lumpur Destination | Al Ghaffar", "Kuala Lumpur Guide", "Essential travel tips and attractions in Kuala Lumpur."),
]

# Patterns for invented claims: years, IATA, awards, unverified prices
CLAIM_PATTERNS = [
    r"\b198[04]\b",
    r"\b(iata|award-winning|#1 agency|best travel)\b",
    r"\b(three decades|40 years)\b",
    r"\$\s*\d+",
    r"\b(pkr|rs\.?)\s*\d+",
]

def main():
    print("=== 13 AL GHAFFAR FIXTURE PAGES: BRAND EXTRACTION & REWRITES ===")
    all_clean = True
    for idx, (url, cur_t, h1, cur_m) in enumerate(fixture_pages, 1):
        brand = extract_brand_from_page(url, cur_t, h1)
        new_t = rewrite_natural_title(cur_t, h1, url)
        new_m = rewrite_natural_meta(cur_m, h1, set(), set(), url)

        combined = f"{new_t} {new_m}".lower()
        invented = [p for p in CLAIM_PATTERNS if re.search(p, combined)]
        status = "PASS (0 invented claims)" if not invented else f"FAIL (found {invented})"
        if invented:
            all_clean = False

        print(f"[{idx:02d}] URL: {url}")
        print(f"     Brand:   {brand}")
        print(f"     Title:   {new_t} ({len(new_t)} chars)")
        print(f"     Meta:    {new_m} ({len(new_m)} chars)")
        print(f"     Status:  {status}")

    print(f"\nFinal Result: {'ALL 13 PAGES VERIFIED CLEAN' if all_clean else 'FAILED'}")
    return 0 if all_clean else 1

if __name__ == "__main__":
    sys.exit(main())
