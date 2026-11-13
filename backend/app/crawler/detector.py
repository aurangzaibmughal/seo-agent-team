import re
from typing import Dict, Any, Tuple, Optional

class PlatformDetector:
    """Deterministic platform detector for CMS and web frameworks."""

    PLATFORMS = ("nextjs", "wordpress", "shopify", "plain_html")

    def __init__(self):
        self.nextjs_signals = 0
        self.wordpress_signals = 0
        self.shopify_signals = 0
        self.total_pages_analyzed = 0
        self.evidence: list[str] = []
        self.detected_subframework: Optional[str] = None

    def analyze_page(self, url: str, status_code: int, headers: Dict[str, str], html: str):
        """Analyzes headers and HTML of a crawled page for framework signatures."""
        if status_code != 200 or not html:
            return

        self.total_pages_analyzed += 1
        headers_lower = {k.lower(): str(v).lower() for k, v in (headers or {}).items()}
        html_lower = html.lower()

        # 1. Next.js detection
        x_powered_by = headers_lower.get("x-powered-by", "")
        if "next.js" in x_powered_by or "nextjs" in x_powered_by:
            self.nextjs_signals += 5
            self.evidence.append(f"Header x-powered-by: {x_powered_by}")
        if "__next_data__" in html_lower or "self.__next_f" in html_lower:
            self.nextjs_signals += 4
            self.evidence.append("Next.js hydration payload (__NEXT_DATA__ / __next_f)")
        if "/_next/" in html_lower or "/_next/static/" in html_lower:
            self.nextjs_signals += 3
            self.evidence.append("Next.js asset paths (/_next/static/)")

        # 2. WordPress & Elementor detection
        if "wordpress" in x_powered_by:
            self.wordpress_signals += 5
            self.evidence.append(f"Header x-powered-by: {x_powered_by}")
        wp_gen_match = re.search(r'<meta[^>]+name=["\']generator["\'][^>]+content=["\']([^"\']*wordpress[^"\']*)["\']', html_lower)
        if wp_gen_match:
            self.wordpress_signals += 5
            self.evidence.append(f"Meta generator WordPress: {wp_gen_match.group(1)}")
        if "/wp-content/" in html_lower or "/wp-includes/" in html_lower:
            self.wordpress_signals += 3
            self.evidence.append("WordPress asset paths (/wp-content/ or /wp-includes/)")
        if "/wp-json/" in html_lower or "wp-json" in headers_lower.get("link", ""):
            self.wordpress_signals += 2
            self.evidence.append("WordPress REST API link (/wp-json/)")

        # Elementor subframework detection
        elem_gen_match = re.search(r'<meta[^>]+name=["\']generator["\'][^>]+content=["\']([^"\']*elementor[^"\']*)["\']', html_lower)
        if elem_gen_match:
            self.wordpress_signals += 5
            self.detected_subframework = "elementor"
            self.evidence.append(f"Meta generator Elementor: {elem_gen_match.group(1)}")
        if "/wp-content/plugins/elementor" in html_lower or "elementor-frontend-js" in html_lower or "elementor-kit-" in html_lower:
            self.wordpress_signals += 3
            self.detected_subframework = "elementor"
            self.evidence.append("Elementor plugin assets and CSS class markers")

        # 3. Shopify detection
        if "cdn.shopify.com" in html_lower or "shopify.theme" in html_lower:
            self.shopify_signals += 5
            self.evidence.append("Shopify CDN assets (cdn.shopify.com)")
        if "myshopify.com" in html_lower or "x-shopid" in headers_lower:
            self.shopify_signals += 4
            self.evidence.append("Shopify store domain / x-shopid header")

    def detect(self) -> Tuple[str, float]:
        """Returns (detected_platform, confidence)."""
        if self.nextjs_signals > 0 and self.nextjs_signals >= max(self.wordpress_signals, self.shopify_signals):
            confidence = 1.0 if self.nextjs_signals >= 5 else min(0.99, 0.70 + (self.nextjs_signals * 0.08))
            return "nextjs", round(confidence, 2)

        if self.wordpress_signals > 0 and self.wordpress_signals >= max(self.nextjs_signals, self.shopify_signals):
            confidence = 1.0 if self.wordpress_signals >= 5 else min(0.99, 0.70 + (self.wordpress_signals * 0.08))
            return "wordpress", round(confidence, 2)

        if self.shopify_signals > 0 and self.shopify_signals >= max(self.nextjs_signals, self.wordpress_signals):
            confidence = 1.0 if self.shopify_signals >= 5 else min(0.99, 0.70 + (self.shopify_signals * 0.08))
            return "shopify", round(confidence, 2)

        # Fallback: Plain HTML
        confidence = 0.65 if self.total_pages_analyzed > 0 else 0.50
        return "plain_html", round(confidence, 2)
