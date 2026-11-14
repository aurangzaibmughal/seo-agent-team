from urllib.parse import urlparse
from typing import Dict

def map_url_to_nextjs_path(url: str, router_type: str = "app") -> Dict[str, str]:
    """Maps a crawled URL to Next.js metadata snippet file path and target file path.
    Always uses .metadata.snippet.tsx so existing app files are never overwritten.
    """
    parsed = urlparse(url)
    path = parsed.path.strip("/")

    if not path:
        if router_type == "pages":
            return {
                "file_path": "pages/index.metadata.snippet.tsx",
                "target_file": "pages/index.tsx",
                "router_type": "pages",
                "note": "Root homepage metadata snippet in Next.js Pages Router"
            }
        return {
            "file_path": "app/page.metadata.snippet.tsx",
            "target_file": "app/page.tsx",
            "router_type": "app",
            "note": "Root page metadata snippet in Next.js App Router"
        }

    parts = path.split("/")

    if router_type == "pages":
        if len(parts) == 1:
            target = f"pages/{parts[0]}.tsx"
            snippet = f"pages/{parts[0]}.metadata.snippet.tsx"
        else:
            target = f"pages/{'/'.join(parts[:-1])}/[slug].tsx"
            snippet = f"pages/{'/'.join(parts[:-1])}/[slug].metadata.snippet.tsx"
        return {
            "file_path": snippet,
            "target_file": target,
            "router_type": "pages",
            "note": f"Likely Pages Router snippet for route '/{path}'"
        }

    # App Router default
    if len(parts) == 1:
        target = f"app/{parts[0]}/page.tsx"
        snippet = f"app/{parts[0]}/page.metadata.snippet.tsx"
    elif parts[0] == "blog" and len(parts) >= 2:
        target = "app/blog/[slug]/page.tsx"
        snippet = "app/blog/[slug]/page.metadata.snippet.tsx"
    elif parts[0] == "portfolio" and len(parts) >= 2:
        target = f"app/portfolio/{parts[1]}/page.tsx"
        snippet = f"app/portfolio/{parts[1]}/page.metadata.snippet.tsx"
    else:
        target = f"app/{'/'.join(parts)}/page.tsx"
        snippet = f"app/{'/'.join(parts)}/page.metadata.snippet.tsx"

    return {
        "file_path": snippet,
        "target_file": target,
        "router_type": "app",
        "note": f"Likely App Router metadata snippet for route '/{path}'"
    }
