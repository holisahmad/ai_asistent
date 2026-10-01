import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI Knowledge Assistant",
  description:
    "Asisten AI knowledge base perusahaan — grounded answers dengan sitasi sumber.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="id">
      <body className="min-h-screen bg-slate-950 text-slate-100 antialiased">
        {children}
      </body>
    </html>
  );
}
