import re
from pathlib import Path
from bs4 import BeautifulSoup
from app.agents.content_agent import (
    resolve_site_brand, validate_rewrite, rewrite_natural_title, rewrite_natural_meta,
    count_brand_occurrences
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

# 13 Al Ghaffar Pages (SYNTHETIC FIXTURES derived from audit structure)
AL_GHAFFAR_13_PAGES = [
    {
        "url": "https://www.alghaffar.com.pk/",
        "title": "Al Ghaffar Travel – Hajj, Umrah & Holiday Tour Packages Karachi",
        "h1": "Al Ghaffar Travel & Tours",
        "meta_desc": "IT Service WordPress Theme",
        "body_text": "Explore top holiday tour packages and Umrah services in Karachi. Providing visa assistance, flight bookings, and family holiday tours."
    },
    {
        "url": "https://www.alghaffar.com.pk/about/",
        "title": "About Us | Al Ghaffar Travel",
        "h1": "About Al Ghaffar Travel",
        "meta_desc": "IT Service WordPress Theme",
        "body_text": "Learn about our travel company history, client commitment, and team values serving religious and leisure travelers across Pakistan."
    },
    {
        "url": "https://www.alghaffar.com.pk/services/",
        "title": "Our Services | Al Ghaffar",
        "h1": "Travel & Tour Services",
        "meta_desc": "IT Service WordPress Theme",
        "body_text": "Comprehensive flight bookings, visa assistance, hotel reservations, and destination management from our Karachi agency."
    },
    {
        "url": "https://www.alghaffar.com.pk/trip/",
        "title": "Holiday Tour Packages | Al Ghaffar",
        "h1": "Curated Holiday Packages",
        "meta_desc": "IT Service WordPress Theme",
        "body_text": "Explore international holiday packages from Karachi. Compare duration and sightseeing options across Sri Lanka, Thailand, and Malaysia."
    },
    {
        "url": "https://www.alghaffar.com.pk/contact/",
        "title": "Contact Us | Al Ghaffar",
        "h1": "Get in Touch with Our Team",
        "meta_desc": "IT Service WordPress Theme",
        "body_text": "Contact our main travel office in DHA Phase 2 Karachi. Call our customer support helpline or visit our branch for reservations."
    },
    {
        "url": "https://www.alghaffar.com.pk/career/",
        "title": "Careers & Jobs | Al Ghaffar",
        "h1": "Join Our Travel Team",
        "meta_desc": "IT Service WordPress Theme",
        "body_text": "Explore current career opportunities and job openings in our Karachi office. Grow your travel consulting career with our team."
    },
    {
        "url": "https://www.alghaffar.com.pk/faqs/",
        "title": "Frequently Asked Questions | Al Ghaffar",
        "h1": "FAQs & Answers",
        "meta_desc": "IT Service WordPress Theme",
        "body_text": "Find answers to common booking questions regarding flight tickets, visa processing times, Umrah requirements, and refund terms."
    },
    {
        "url": "https://www.alghaffar.com.pk/destinations/sri-lanka/",
        "title": "Sri Lanka Tour Packages | Al Ghaffar",
        "h1": "Sri Lanka Vacation Packages",
        "meta_desc": "IT Service WordPress Theme",
        "body_text": "Discover scenic Sri Lanka holiday packages from Karachi. Explore Colombo, Kandy, and Bentota beaches with personalized quotes."
    },
    {
        "url": "https://www.alghaffar.com.pk/trip/thailand/",
        "title": "Thailand Holiday Package | Al Ghaffar",
        "h1": "Thailand Tour Packages",
        "meta_desc": "IT Service WordPress Theme",
        "body_text": "Enjoy 6-day Thailand family vacations from Karachi covering Bangkok city sightseeing and Pattaya beaches with inclusive hotel stays."
    },
    {
        "url": "https://www.alghaffar.com.pk/trip/sri-lanka/",
        "title": "Sri Lanka Travel Deals | Al Ghaffar",
        "h1": "Sri Lanka Tour Offers",
        "meta_desc": "IT Service WordPress Theme",
        "body_text": "5-day Sri Lanka holiday package from Karachi. View full sightseeing itineraries, hotel accommodations, and guided travel details."
    },
    {
        "url": "https://www.alghaffar.com.pk/destinations/thailand/",
        "title": "Thailand Travel Guide | Al Ghaffar",
        "h1": "Thailand Guide & Packages",
        "meta_desc": "IT Service WordPress Theme",
        "body_text": "Explore Thailand holiday destinations from Karachi. Compare vacation packages, seasonal travel deals, and destination highlights."
    },
    {
        "url": "https://www.alghaffar.com.pk/trip/kuala-lumpur/",
        "title": "Kuala Lumpur Tours | Al Ghaffar",
        "h1": "Kuala Lumpur Packages",
        "meta_desc": "IT Service WordPress Theme",
        "body_text": "6-day Kuala Lumpur holiday packages from Karachi. Explore Petronas Towers, Genting Highlands, and urban shopping destinations."
    },
    {
        "url": "https://www.alghaffar.com.pk/destinations/kuala-kumpur/",
        "title": "Kuala Lumpur Destination | Al Ghaffar",
        "h1": "Kuala Lumpur Guide",
        "meta_desc": "IT Service WordPress Theme",
        "body_text": "Complete destination travel guide for Kuala Lumpur Malaysia. Discover top city attractions, transit tips, and vacation planning."
    }
]

INVENTED_CLAIM_PATTERNS = [
    r"\b198[04]\b",
    r"\b(iata|award-winning|#1 agency|best travel)\b",
    r"\b(three decades|40 years)\b",
    r"\$\s*\d+",
    r"\b(pkr|rs\.?)\s*\d+",
]

def test_single_brand_resolution_across_alghaffar():
    """Confirms resolve_site_brand resolves exactly ONE brand across all 13 pages."""
    brand = resolve_site_brand(AL_GHAFFAR_13_PAGES, "https://www.alghaffar.com.pk/")
    assert brand == "Al Ghaffar Travel"

def test_rewrites_quality_13_alghaffar_pages():
    """Tests all 13 Al Ghaffar pages for brand consistency, length bounds,
    grounding, no dangling endings, and zero invented claims.
    """
    brand = resolve_site_brand(AL_GHAFFAR_13_PAGES, "https://www.alghaffar.com.pk/")
    assert brand == "Al Ghaffar Travel"

    for page in AL_GHAFFAR_13_PAGES:
        url = page["url"]
        cur_t = page["title"]
        h1 = page["h1"]
        cur_m = page["meta_desc"]
        page_text = f"{cur_t} {h1} {page['body_text']}"

        new_t = rewrite_natural_title(cur_t, h1, url, page_text=page_text, brand=brand)
        new_m = rewrite_natural_meta(cur_m, h1, url=url, page_text=page_text, brand=brand)

        # 1. Brand consistency: brand must appear exactly once in title
        assert brand.lower() in new_t.lower()
        assert new_t.lower().count(brand.lower()) == 1

        # 2. Title length bounds (40-60 chars) or fail-closed skeleton
        if "needs manual rewrite" not in new_t.lower():
            assert 40 <= len(new_t) <= 60, f"Title length {len(new_t)} out of 40-60 on {url}: '{new_t}'"

        # 3. Meta length bounds (120-155 chars) or fail-closed skeleton
        if "needs manual rewrite" not in new_m.lower():
            assert 120 <= len(new_m) <= 155, f"Meta length {len(new_m)} out of 120-155 on {url}: '{new_m}'"
            assert brand.lower() in new_m.lower()

        # 4. Zero dangling stopword endings
        for text_val in [new_t, new_m]:
            last_word = re.findall(r"\b[A-Za-z0-9\-]+\b", text_val)[-1].lower()
            assert last_word not in {"for", "and", "with", "the", "of", "to", "in", "on", "at", "by", "from", "a", "an"}, \
                f"Dangling ending '{last_word}' in: {text_val}"

        # 5. Zero invented claims
        combined = f"{new_t} {new_m}".lower()
        for pat in INVENTED_CLAIM_PATTERNS:
            match = re.search(pat, combined)
            assert not match, f"Invented claim '{match.group(0)}' found on {url}"

def test_rewrites_quality_non_travel_fixtures():
    """Proves generic rewrite engine on Next.js, Shopify, Dental Clinic, and SaaS Landing Page."""
    fixtures = [
        ("nextjs-fixture.html", "https://nextjs-saas-platform.example.com/"),
        ("shopify-fixture.html", "https://shopify-store.example.com/"),
        ("dental-fixture.html", "https://clifton-dental.example.com/"),
        ("saas-fixture.html", "https://cloudmetrics.example.com/")
    ]

    for fname, url in fixtures:
        fpath = FIXTURES_DIR / "generic" / fname
        assert fpath.exists(), f"Fixture {fpath} must exist"
        html = fpath.read_text(encoding="utf-8")
        soup = BeautifulSoup(html, "html.parser")

        cur_t = soup.title.string.strip() if soup.title else ""
        meta_tag = soup.find("meta", attrs={"name": "description"})
        cur_m = meta_tag["content"].strip() if meta_tag and "content" in meta_tag.attrs else ""
        h1_tag = soup.find("h1")
        h1 = h1_tag.get_text().strip() if h1_tag else ""
        body_text = soup.body.get_text().strip() if soup.body else ""
        og_tag = soup.find("meta", attrs={"property": "og:site_name"})
        og_site_name = og_tag["content"].strip() if og_tag and "content" in og_tag.attrs else ""

        page = {"url": url, "title": cur_t, "meta_desc": cur_m, "h1": h1, "body_text": body_text, "og_site_name": og_site_name}
        brand = resolve_site_brand([page], url)

        page_text = f"{cur_t} {h1} {body_text}"
        new_t = rewrite_natural_title(cur_t, h1, url, page_text=page_text, brand=brand)
        new_m = rewrite_natural_meta(cur_m, h1, url=url, page_text=page_text, brand=brand)

        # Must not contain travel buzzwords on non-travel sites
        assert "itinerary" not in new_t.lower()
        assert "itinerary" not in new_m.lower()
        assert "tour" not in new_t.lower()
        assert "tour" not in new_m.lower()

        # Must pass validator or fail closed cleanly
        if "needs manual rewrite" not in new_t.lower():
            assert 50 <= len(new_t) <= 60
            assert brand.lower() in new_t.lower()
        if "needs manual rewrite" not in new_m.lower():
            assert 120 <= len(new_m) <= 155
            total_b, _ = count_brand_occurrences(new_m, brand)
            assert total_b <= 1

def test_validator_fails_on_length_violations():
    """Validator must strictly reject titles <50 or >60 and metas <120 or >155."""
    page_text = "Sample company providing reliable web engineering services in London UK."
    brand = "Acme Corp"

    # Too short title (40 chars)
    short_t = "Short Title | Acme Corp"
    valid, reason = validate_rewrite(short_t, page_text, brand, 50, 60, is_title=True)
    assert not valid
    assert "below minimum" in reason

    # Too long title (65 chars)
    long_t = "This Is An Extremely Long Title Tag That Exceeds Sixty Chars | Acme Corp"
    valid, reason = validate_rewrite(long_t, page_text, brand, 50, 60, is_title=True)
    assert not valid
    assert "exceeds maximum" in reason

def test_validator_fails_on_dangling_stopword_endings():
    """Validator must reject rewrites ending with prepositions or stopwords."""
    page_text = "Sample company providing reliable web engineering services in London UK."
    brand = "Acme Corp"

    dangling_meta = "Explore reliable web engineering and development solutions for modern digital infrastructure across London UK with Acme Corp with."
    valid, reason = validate_rewrite(dangling_meta, page_text, brand, 100, 155, is_title=False)
    assert not valid
    assert "Dangling stopword" in reason

def test_validator_fails_on_ungrounded_words():
    """Validator must reject rewrites where >= 20% content words are invented."""
    page_text = "Dental clinic offering teeth cleanings and checkups."
    brand = "Apex Dental"

    invented_meta = "Apex Dental provides automated artificial intelligence quantum cryptography serverless microservices for banking."
    valid, reason = validate_rewrite(invented_meta, page_text, brand, 100, 155, is_title=False)
    assert not valid
    assert "Grounding check failed" in reason

def test_validator_fails_on_banned_marketing_copy():
    """Validator must reject any rewrite containing the 11 banned marketing buzzwords."""
    page_text = "Sample page text about services and products."
    brand = "Acme Corp"

    banned_words = [
        "verified", "official", "transparent", "dedicated", "custom",
        "digital growth", "digital agency", "enterprise", "itinerary", "award", "best"
    ]
    for b in banned_words:
        cand = f"Acme Corp delivers {b} solutions for clients across our main regions."
        valid, reason = validate_rewrite(cand, page_text, brand, 30, 155, is_title=False)
        assert not valid
        assert "Banned marketing copy" in reason

def test_rewrites_quality_alghaffar_real_fixtures():
    """Validates rewrite engine against real minimal fixtures captured directly from https://www.alghaffar.com.pk/."""
    real_fixtures_dir = FIXTURES_DIR / "alghaffar_real"
    assert real_fixtures_dir.exists(), "alghaffar_real directory must exist"
    fixture_files = sorted(real_fixtures_dir.glob("*.html"))
    assert len(fixture_files) == 13, f"Expected 13 real fixture files, found {len(fixture_files)}"

    for fpath in fixture_files:
        html = fpath.read_text(encoding="utf-8")
        soup = BeautifulSoup(html, "html.parser")
        cur_t = soup.title.string.strip() if soup.title else ""
        meta_tag = soup.find("meta", attrs={"name": "description"})
        cur_m = meta_tag["content"].strip() if meta_tag and "content" in meta_tag.attrs else ""
        h1_tag = soup.find("h1")
        h1 = h1_tag.get_text().strip() if h1_tag else ""
        body_text = soup.body.get_text().strip() if soup.body else ""
        og_tag = soup.find("meta", attrs={"property": "og:site_name"})
        og_name = og_tag["content"].strip() if og_tag and "content" in og_tag.attrs else "Al Ghaffar Travel"

        canonical_tag = soup.find("link", attrs={"rel": "canonical"})
        url = canonical_tag["href"].strip() if canonical_tag and "href" in canonical_tag.attrs else "https://www.alghaffar.com.pk/"

        page = {"url": url, "title": cur_t, "meta_desc": cur_m, "h1": h1, "body_text": body_text, "og_site_name": og_name}
        brand = resolve_site_brand([page], url)

        page_text = f"{cur_t} {h1} {body_text}"
        new_t = rewrite_natural_title(cur_t, h1, url, page_text=page_text, brand=brand)
        new_m = rewrite_natural_meta(cur_m, h1, url=url, page_text=page_text, brand=brand)

        if "needs manual rewrite" not in new_t.lower():
            assert 40 <= len(new_t) <= 60
            assert brand.lower() in new_t.lower()
        if "needs manual rewrite" not in new_m.lower():
            assert 120 <= len(new_m) <= 155
            total_b, _ = count_brand_occurrences(new_m, brand)
            assert total_b <= 1

def test_validator_rejects_old_bad_outputs():
    """Confirms validator strictly rejects past inaccurate, repetitive, or ungrounded outputs."""
    brand = "Al Ghaffar Travel"
    page_text = (
        "Explore international holiday packages from Karachi. Compare duration and sightseeing options across Sri Lanka. "
        "Our travel services include flight bookings, visa assistance, hotel reservations, and destination management."
    )

    bad_titles = [
        "Our Services - Al Ghaffar Services | Al Ghaffar Travel",  # Short brand repetition and padding
        "Holiday Tour Packages - Al Ghaffar | Al Ghaffar Travel",  # - Al Ghaffar padding
        "& Tours | Al Ghaffar Travel",                            # Fragment as H1/subject
        "Hajj, Umrah & Holiday Tour Packages Karachi | Al Ghaffar Travel", # Too long (>60 chars, 63)
        "Short Title | Al Ghaffar Travel",                         # Too short (<40 chars, 32)
        "Holiday Tour Packages | Al Ghaffar Travel | Tours",       # Multiple delimiters / fragments
        "Holiday Tour Packages | Al Ghaffar",                      # Incomplete brand
        "Curated Holiday Packages - Trip | Al Ghaffar Travel",     # URL-slug token padding (- Trip)
        "Kuala Lumpur Guide - Kuala Kumpur | Al Ghaffar Travel",   # URL-slug typo padding (- Kuala Kumpur)
        "View Full Sightseeing Itineraries | Al Ghaffar Travel",   # Starts with CTA verb + missing H1 primary topic
    ]

    for bad_t in bad_titles:
        valid, reason = validate_rewrite(
            bad_t, page_text, brand, min_len=40, max_len=60, is_title=True, current_t="Holiday Tour Packages | Al Ghaffar", h1="Sri Lanka Vacation Packages"
        )
        assert not valid, f"Expected title to be REJECTED but passed: '{bad_t}'"

    bad_metas = [
        # Concatenates title + H1 into sentence with pipe '|', repeated brand forms
        "Holiday Tour Packages | Al Ghaffar Curated Holiday Packages Explore international holiday packages from Karachi with Al Ghaffar Travel.",
        # Contains pipe delimiter
        "Explore top holiday tour packages | Al Ghaffar Travel with family vacation offers and hotel bookings across Sri Lanka and Thailand.",
        # Starts with title
        "Holiday Tour Packages are available from Karachi with Al Ghaffar Travel covering international flights and hotel bookings.",
        # Starts with H1
        "Curated Holiday Packages are available from Karachi with Al Ghaffar Travel covering international flights and hotel bookings.",
        # Uses '- Brand.' padding instead of sentence
        "Explore international holiday packages from Karachi and compare duration across Sri Lanka and Thailand - Al Ghaffar Travel.",
        # Fragment '& Tours' used
        "Needs manual rewrite: insufficient page text to generate 120-155 character meta without inventing copy (& Tours | Al Ghaffar Travel).",
        # Missing terminating punctuation
        "Explore international holiday packages from Karachi compare duration and plan your family vacation with Al Ghaffar Travel",
        # Multiple brand occurrences
        "Al Ghaffar Travel offers international holiday packages from Karachi with Al Ghaffar Travel for family vacations.",
        # Too short (<120)
        "Explore international holiday packages from Karachi with Al Ghaffar Travel.",
        # Too long (>155)
        "Explore international holiday packages from Karachi with Al Ghaffar Travel and compare comprehensive duration and sightseeing options across Sri Lanka, Thailand, and Malaysia with our consultants.",
    ]

    for bad_m in bad_metas:
        valid, reason = validate_rewrite(
            bad_m, page_text, brand, min_len=120, max_len=155, is_title=False, current_t="Holiday Tour Packages | Al Ghaffar", h1="Sri Lanka Vacation Packages"
        )
        assert not valid, f"Expected meta to be REJECTED but passed: '{bad_m}' (reason: {reason})"

def test_generate_alghaffar_b01_table_markdown():
    """Generates the grounded B-01 results as a plain text list (NOT markdown table to avoid pipe breakage),
    as well as output for Dental Clinic and SaaS fixtures.
    """
    brand = resolve_site_brand(AL_GHAFFAR_13_PAGES, "https://www.alghaffar.com.pk/")
    items = []
    for idx, page in enumerate(AL_GHAFFAR_13_PAGES, 1):
        url = page["url"]
        path_label = url.replace("https://www.alghaffar.com.pk", "") or "/"
        cur_t = page["title"]
        h1 = page["h1"]
        cur_m = page["meta_desc"]
        page_text = f"{cur_t} {h1} {page['body_text']}"
        new_t = rewrite_natural_title(cur_t, h1, url, page_text=page_text, brand=brand)
        new_m = rewrite_natural_meta(cur_m, h1, url=url, page_text=page_text, brand=brand)
        
        t_valid, t_reason = validate_rewrite(new_t, page_text, brand, 40, 60, is_title=True, current_t=cur_t, h1=h1)
        m_valid, m_reason = validate_rewrite(new_m, page_text, brand, 120, 155, is_title=False, current_t=cur_t, h1=h1)
        
        items.append(
            f"{idx}. Page: {path_label}\n"
            f"   - Recommended Title: {new_t} ({len(new_t)} chars) [{'Valid' if t_valid else 'Needs Manual Rewrite: ' + t_reason}]\n"
            f"   - Recommended Meta: {new_m} ({len(new_m)} chars) [{'Valid' if m_valid else 'Needs Manual Rewrite: ' + m_reason}]"
        )
    
    plain_list = "\n".join([
        "=== AL GHAFFAR 13-PAGE SUGGESTED DRAFTS: REVIEW BEFORE USE ===",
        *items,
        "=============================================================="
    ])
    print("\n" + plain_list + "\n")
    assert len(items) == 13

    # Non-travel fixtures (Dental & SaaS)
    non_travel_outputs = []
    for fname, url in [("dental-fixture.html", "https://clifton-dental.example.com/"), ("saas-fixture.html", "https://cloudmetrics.example.com/")]:
        fpath = FIXTURES_DIR / "generic" / fname
        html = fpath.read_text(encoding="utf-8")
        soup = BeautifulSoup(html, "html.parser")
        cur_t = soup.title.string.strip() if soup.title else ""
        meta_tag = soup.find("meta", attrs={"name": "description"})
        cur_m = meta_tag["content"].strip() if meta_tag and "content" in meta_tag.attrs else ""
        h1_tag = soup.find("h1")
        h1 = h1_tag.get_text().strip() if h1_tag else ""
        body_text = soup.body.get_text().strip() if soup.body else ""
        og_tag = soup.find("meta", attrs={"property": "og:site_name"})
        og_site_name = og_tag["content"].strip() if og_tag and "content" in og_tag.attrs else ""
        page = {"url": url, "title": cur_t, "meta_desc": cur_m, "h1": h1, "body_text": body_text, "og_site_name": og_site_name}
        brand = resolve_site_brand([page], url)
        page_text = f"{cur_t} {h1} {body_text}"
        new_t = rewrite_natural_title(cur_t, h1, url, page_text=page_text, brand=brand)
        new_m = rewrite_natural_meta(cur_m, h1, url=url, page_text=page_text, brand=brand)
        non_travel_outputs.append(f"{fname} -> Resolved Brand: {brand} | Title: '{new_t}' ({len(new_t)} chars) | Meta: '{new_m}' ({len(new_m)} chars)")

    print("\n--- NON-TRAVEL FIXTURES PLAIN LIST ---\n" + "\n".join(non_travel_outputs) + "\n--------------------------------------\n")
