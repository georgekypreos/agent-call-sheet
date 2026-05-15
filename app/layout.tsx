import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Agent Call Sheet",
  description: "Daily SREG agent call list — FUB + Courted dashboard",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        {/* canvas-confetti loaded from CDN; fallback runs if blocked */}
        <script src="https://cdnjs.cloudflare.com/ajax/libs/canvas-confetti/1.9.3/confetti.browser.min.js" async />
      </head>
      <body className="font-sans">{children}</body>
    </html>
  );
}
