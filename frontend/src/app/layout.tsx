import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "SEO Agent Team — Multi-Agent SEO Engine",
  description: "Autonomous agent team running end-to-end SEO workflows: crawl, audit, strategy, content, code fixes, and reports.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-[#070b14] text-slate-100 antialiased selection:bg-indigo-500 selection:text-white">
        {children}
      </body>
    </html>
  );
}
