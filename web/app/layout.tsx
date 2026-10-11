import type { Metadata } from "next";
import localFont from "next/font/local";
import { ThemeProvider } from "next-themes";
import { UploadProvider } from "@/components/inbox/upload";
import { TopNav } from "@/components/shell/nav";
import "./globals.css";

// Instrument Sans (SIL Open Font License, see app/fonts/OFL.txt), shipped in the repo: no font is fetched from the internet.
const sans = localFont({ src: "./fonts/instrument-sans-latin-wght.woff2", weight: "400 700", variable: "--font-instrument", display: "swap" });

export const metadata: Metadata = {
  title: "Call compliance",
  description: "Self-hosted compliance review of bank phone calls.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={sans.variable} suppressHydrationWarning>
      <body>
        <ThemeProvider attribute="class" defaultTheme="dark" enableSystem disableTransitionOnChange>
          <UploadProvider>
            <TopNav />
            <main className="mx-auto max-w-[1400px] px-4 py-6">{children}</main>
          </UploadProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
