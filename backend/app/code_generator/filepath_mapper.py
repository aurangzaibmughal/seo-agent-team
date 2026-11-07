from urllib.parse import urlparse
from typing import Dict, Any, List

def map_url_to_nextjs_path(url: str, router_type: str = "app") -> Dict[str, str]:
    """Maps a crawled URL to likely Next.js file path(s).
    Shown as a suggestion, not a guarantee.
    """
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    
    if not path:
        if router_type == "pages":
            return {
                "file_path": "pages/index.tsx",
                "router_type": "pages",
                "note": "Root homepage view in Next.js Pages Router"
            }
        return {
            "file_path": "app/page.tsx",
            "router_type": "app",
            "note": "Root page component in Next.js App Router"
        }

    parts = path.split("/")
    
    if router_type == "pages":
        if len(parts) == 1:
            file_path = f"pages/{parts[0]}.tsx"
        else:
            file_path = f"pages/{'/'.join(parts[:-1])}/[slug].tsx"
        return {
            "file_path": file_path,
            "router_type": "pages",
            "note": f"Likely Pages Router template for route '/{path}'"
        }

    # App Router default
    if len(parts) == 1:
        file_path = f"app/{parts[0]}/page.tsx"
    elif parts[0] == "blog" and len(parts) == 2:
        file_path = "app/blog/[slug]/page.tsx"
    elif parts[0] == "portfolio" and len(parts) == 2:
        file_path = f"app/portfolio/{parts[1]}/page.tsx"
    else:
        file_path = f"app/{'/'.join(parts)}/page.tsx"

    return {
        "file_path": file_path,
        "router_type": "app",
        "note": f"Likely App Router page component for route '/{path}'"
    }
