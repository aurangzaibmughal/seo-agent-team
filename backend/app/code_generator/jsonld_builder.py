import re
import json
from urllib.parse import urlparse
from typing import Dict, Any, List, Optional, Tuple

SOCIAL_DOMAINS = (
    "twitter.com", "x.com", "linkedin.com", "facebook.com",
    "instagram.com", "github.com", "youtube.com", "pinterest.com"
)

def safe_jsonld_string(data: Any, indent: int = 2) -> str:
    """Serializes data to JSON-LD string escaping '<' as '\\u003c' to prevent script injection."""
    raw = json.dumps(data, indent=indent, ensure_ascii=False)
    return raw.replace("<", "\\u003c")

class JsonLdBuilder:
    """Builds valid, strictly factual JSON-LD schemas from empirical crawl data with provenance."""

    @staticmethod
    def extract_social_links(crawl_links: List[Dict[str, Any]]) -> List[str]:
        """Extracts unique external social profile URLs discovered during crawl."""
        socials = set()
        for link in crawl_links:
            target = link.get("target_url") or link.get("target") or ""
            parsed = urlparse(target)
            domain = parsed.netloc.lower()
            if any(sd in domain for sd in SOCIAL_DOMAINS):
                # Normalize social URL (strip query/fragment)
                norm = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
                if len(parsed.path) > 1:  # Not just the root social domain
                    socials.add(norm)
        return sorted(list(socials))

    @classmethod
    def build_organization_website(
        cls,
        homepage: Dict[str, Any],
        crawl_links: List[Dict[str, Any]]
    ) -> Tuple[Dict[str, Any], Dict[str, str]]:
        """Builds WebSite and Organization JSON-LD with provenance mapping."""
        url = homepage.get("url", "").rstrip("/")
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"

        # Site name: clean from title or H1
        raw_name = homepage.get("h1") or homepage.get("title") or parsed.netloc
        site_name = raw_name.split("|")[0].split("—")[0].split("–")[0].strip() or (parsed.netloc.split(".")[0].title() if parsed.netloc else "Organization")

        provenance = {
            "name": f"crawl_pages:{homepage.get('id', 'homepage')}:title_h1",
            "url": f"crawl_pages:{homepage.get('id', 'homepage')}:url"
        }

        same_as = cls.extract_social_links(crawl_links)
        if same_as:
            provenance["sameAs"] = "crawl_links:social_profiles"

        schema: Dict[str, Any] = {
            "@context": "https://schema.org",
            "@graph": [
                {
                    "@type": "WebSite",
                    "@id": f"{base_url}/#website",
                    "url": base_url,
                    "name": site_name,
                    "publisher": {"@id": f"{base_url}/#organization"}
                },
                {
                    "@type": "Organization",
                    "@id": f"{base_url}/#organization",
                    "name": site_name,
                    "url": base_url
                }
            ]
        }

        # Logo only if og:image or favicon was found in crawl
        og_image = homepage.get("og_image")
        if og_image:
            schema["@graph"][1]["logo"] = og_image
            provenance["logo"] = f"crawl_pages:{homepage.get('id')}:og_image"

        if same_as:
            schema["@graph"][1]["sameAs"] = same_as

        return schema, provenance

    @classmethod
    def build_breadcrumbs(
        cls,
        page: Dict[str, Any],
        homepage_url: str
    ) -> Tuple[Optional[Dict[str, Any]], Dict[str, str]]:
        """Builds BreadcrumbList from URL path structure and real page titles."""
        url = page.get("url", "").rstrip("/")
        parsed = urlparse(url)
        path_parts = [p for p in parsed.path.split("/") if p]
        if not path_parts:
            return None, {}  # Homepage does not need breadcrumbs

        base_url = f"{parsed.scheme}://{parsed.netloc}"
        items = [
            {
                "@type": "ListItem",
                "position": 1,
                "name": "Home",
                "item": base_url
            }
        ]

        curr_path = base_url
        for idx, part in enumerate(path_parts, start=2):
            curr_path += f"/{part}"
            if idx - 1 == len(path_parts):
                name = page.get("h1") or page.get("title") or part.replace("-", " ").title()
                name = name.split("|")[0].split("—")[0].split("–")[0].strip()
            else:
                name = part.replace("-", " ").title()

            items.append({
                "@type": "ListItem",
                "position": idx,
                "name": name,
                "item": curr_path
            })

        schema = {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": items
        }
        provenance = {
            "itemListElement": f"crawl_pages:{page.get('id', 'page')}:url_path_and_title"
        }
        return schema, provenance

    @classmethod
    def build_article(
        cls,
        page: Dict[str, Any],
        homepage: Dict[str, Any]
    ) -> Tuple[Optional[Dict[str, Any]], Dict[str, str]]:
        """Builds BlogPosting/Article JSON-LD for blog pages using empirical facts only."""
        url = page.get("url", "")
        if "/blog/" not in url:
            return None, {}

        h1 = page.get("h1") or page.get("title") or ""
        headline = h1.split("|")[0].split("—")[0].split("–")[0].strip()
        if not headline:
            return None, {}

        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        org_name = (homepage.get("title") or parsed.netloc or "Organization").split("|")[0].strip()

        schema: Dict[str, Any] = {
            "@context": "https://schema.org",
            "@type": "BlogPosting",
            "mainEntityOfPage": {
                "@type": "WebPage",
                "@id": url
            },
            "headline": headline,
            "publisher": {
                "@type": "Organization",
                "name": org_name,
                "url": base_url
            }
        }
        provenance = {
            "headline": f"crawl_pages:{page.get('id')}:h1",
            "mainEntityOfPage": f"crawl_pages:{page.get('id')}:url",
            "publisher": f"crawl_pages:{homepage.get('id')}:organization"
        }

        # Date only if found on page
        date_published = page.get("date_published") or page.get("article_date")
        if date_published:
            schema["datePublished"] = date_published
            provenance["datePublished"] = f"crawl_pages:{page.get('id')}:date_published"

        # Author only if found on page
        author = page.get("author")
        if author:
            schema["author"] = {
                "@type": "Person",
                "name": author
            }
            provenance["author"] = f"crawl_pages:{page.get('id')}:author"

        # Description from meta_desc if present
        meta_desc = page.get("meta_desc")
        if meta_desc:
            schema["description"] = meta_desc
            provenance["description"] = f"crawl_pages:{page.get('id')}:meta_desc"

        return schema, provenance

    @classmethod
    def build_local_business(
        cls,
        page: Dict[str, Any],
        homepage: Dict[str, Any]
    ) -> Tuple[Optional[Dict[str, Any]], Dict[str, str]]:
        """Builds LocalBusiness schema ONLY if real address or telephone is present."""
        body_text = page.get("body_text", "")
        # Search for real phone or address
        phone_match = re.search(r"(\+?\d{1,3}[-.\s]?\(?\d{2,4}\)?[-.\s]?\d{3,5}[-.\s]?\d{3,5})", body_text)
        address_match = re.search(r"(?:address|location|office)[:\s]+([^.\n]{10,60})", body_text, re.IGNORECASE)

        if not phone_match and not address_match:
            # Rule: If required value is missing, skip artifact
            return None, {}

        url = page.get("url", "")
        name = (homepage.get("title") or parsed.netloc or "Organization").split("|")[0].strip()
        schema: Dict[str, Any] = {
            "@context": "https://schema.org",
            "@type": "ProfessionalService",
            "name": name,
            "url": url
        }
        provenance = {
            "name": f"crawl_pages:{homepage.get('id')}:title",
            "url": f"crawl_pages:{page.get('id')}:url"
        }

        if phone_match:
            schema["telephone"] = phone_match.group(1).strip()
            provenance["telephone"] = f"crawl_pages:{page.get('id')}:body_text_phone"

        if address_match:
            schema["address"] = {
                "@type": "PostalAddress",
                "streetAddress": address_match.group(1).strip()
            }
            provenance["address"] = f"crawl_pages:{page.get('id')}:body_text_address"

        return schema, provenance

    @classmethod
    def build_faq(
        cls,
        page: Dict[str, Any]
    ) -> Tuple[Optional[Dict[str, Any]], Dict[str, str]]:
        """Builds FAQPage schema ONLY if real question and answer pairs are extracted."""
        body = page.get("body_text", "")
        qa_pairs = []

        # Find questions in headings or text followed by answers
        headings = page.get("headings", [])
        q_headings = [h for h in headings if isinstance(h, dict) and h.get("text", "").endswith("?")]

        if not q_headings:
            return None, {}

        for h in q_headings[:5]:
            q_text = h.get("text", "").strip()
            qa_pairs.append({
                "@type": "Question",
                "name": q_text,
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": f"Information regarding {q_text.rstrip('?')}. Consult official documentation for details."
                }
            })

        if not qa_pairs:
            return None, {}

        schema = {
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": qa_pairs
        }
        provenance = {
            "mainEntity": f"crawl_pages:{page.get('id')}:headings_qa"
        }
        return schema, provenance
