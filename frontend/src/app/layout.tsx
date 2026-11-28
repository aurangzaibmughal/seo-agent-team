import type { Metadata } from "next";
import "./globals.css";

/* ──────────────────────────────────────────────
   SEO META TAGS — Open Graph, Twitter, Favicon,
   Canonical, Robots, Structured Data
   ────────────────────────────────────────────── */

export const metadata: Metadata = {
  // ── Basic ──
  title: "SEO Agent Team — Multi-Agent SEO Engine",
  description:
    "Autonomous agent team running end-to-end SEO workflows: crawl, audit, strategy, content, code fixes, and reports.",
  keywords: [
    "SEO tool",
    "SEO audit",
    "multi-agent SEO",
    "technical SEO",
    "content optimization",
    "SEO automation",
    "website audit",
    "AI SEO",
  ],
  authors: [{ name: "SEO Agent Team" }],
  creator: "SEO Agent Team",
  publisher: "SEO Agent Team",

  // ── Canonical URL ──
  metadataBase: new URL("https://seo-agent-team-psi.vercel.app"),
  alternates: {
    canonical: "/",
  },

  // ── Open Graph (Facebook, LinkedIn, WhatsApp) ──
  openGraph: {
    type: "website",
    title: "SEO Agent Team — Multi-Agent SEO Engine",
    description:
      "Autonomous AI agents that crawl, audit, strategize, write content, fix code, and generate reports — all in one workflow.",
    url: "https://seo-agent-team-psi.vercel.app",
    siteName: "SEO Agent Team",
    images: [
      {
        url: "/og-image.png",
        width: 1200,
        height: 630,
        alt: "SEO Agent Team — Multi-Agent SEO Engine Dashboard",
        type: "image/png",
      },
    ],
    locale: "en_US",
  },

  // ── Twitter Card ──
  twitter: {
    card: "summary_large_image",
    title: "SEO Agent Team — Multi-Agent SEO Engine",
    description:
      "Autonomous AI agents that crawl, audit, strategize, write content, fix code, and generate reports.",
    images: ["/og-image.png"],
  },

  // ── Favicon & Icons ──
  icons: {
    icon: [
      { url: "/favicon.ico", sizes: "any" },
      { url: "/icon.svg", type: "image/svg+xml" },
    ],
    apple: "/apple-touch-icon.png",
  },

  // ── Robots ──
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
      "max-video-preview": -1,
      "max-image-preview": "large",
      "max-snippet": -1,
    },
  },

  // ── Category ──
  category: "technology",
};

/* ── JSON-LD Structured Data ── */
const jsonLd = {
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  name: "SEO Agent Team",
  description:
    "Autonomous multi-agent SEO engine that crawls, audits, strategizes, generates content, fixes code, and exports reports.",
  url: "https://seo-agent-team-psi.vercel.app",
  applicationCategory: "BusinessApplication",
  operatingSystem: "Web",
  offers: {
    "@type": "Offer",
    price: "0",
    priceCurrency: "USD",
  },
  featureList: [
    "Technical SEO Audit",
    "Keyword Research & Gap Analysis",
    "30-Day SEO Strategy",
    "Content Writing & Rewrites",
    "Code Generation for SEO Fixes",
    "Performance Analysis",
    "Multi-Format Report Export",
  ],
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-[#070b14] text-slate-100 antialiased selection:bg-indigo-500 selection:text-white">
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
        />
        {children}
      </body>
    </html>
  );
}
