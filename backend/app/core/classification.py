import re
from urllib.parse import urlparse
from typing import Optional

UTILITY_SLUGS = {
    "login", "signin", "sign-in", "log-in",
    "signup", "sign-up", "register", "registration",
    "admin", "administrator", "gateway",
    "account", "my-account", "profile", "user",
    "cart", "checkout", "basket", "bag",
    "dashboard", "settings", "preferences",
    "auth", "authentication", "portal",
    "password-reset", "reset-password", "forgot-password",
}

CONTENT_SLUGS = {
    "", "home", "about", "about-us", "services", "service",
    "pricing", "plans", "blog", "posts", "articles", "news",
    "portfolio", "case-studies", "work", "projects",
    "contact", "contact-us", "features", "solutions",
    "docs", "documentation", "faq", "faqs", "help",
    "privacy", "privacy-policy", "terms", "terms-of-service"
}

def classify_page_type(url: Optional[str]) -> str:
    """Classifies a URL into 'utility' (private/admin/auth/cart/account) or 'content'.
    
    Rules:
    - Root URL ('/') is always 'content'.
    - Pages matching utility patterns (login, signup, admin, account, cart, checkout, dashboard) are 'utility'.
    - All other pages (services, blog, pricing, portfolio, about, contact) are 'content'.
    """
    if not url:
        return "content"
    
    path = urlparse(url).path.lower().strip()
    if path.endswith("/"):
        path = path[:-1]
    if not path or path == "":
        return "content"
        
    segments = [s for s in path.split("/") if s]
    for seg in segments:
        clean_seg = re.sub(r'[^a-z0-9\-]', '', seg)
        if clean_seg in UTILITY_SLUGS:
            return "utility"
            
    return "content"

def is_admin_page(url: Optional[str]) -> bool:
    """Checks whether URL represents an administrative or gateway portal."""
    if not url:
        return False
    path = urlparse(url).path.lower()
    return bool(re.search(r'/(admin|administrator|gateway)\b', path))
