import type { Metadata } from "next";
import localFont from "next/font/local";
import { ThemeProvider } from "next-themes";
import { DemoBar } from "@/components/shell/demo-bar";
import { TopNav } from "@/components/shell/nav";
import "./globals.css";

// Instrument Sans (SIL Open Font License, see app/fonts/OFL.txt), shipped in the repo: no font is fetched from the internet.
const sans = localFont({ src: "./fonts/instrument-sans-latin-wght.woff2", weight: "400 700", variable: "--font-instrument", display: "swap" });

export const metadata: Metadata = {
  title: "Sentinel",
  description: "Self-hosted compliance review of bank phone calls.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={sans.variable} suppressHydrationWarning>
      <body>
        <ThemeProvider attribute="class" defaultTheme="dark" enableSystem disableTransitionOnChange>
          <TopNav />
          <main className="mx-auto max-w-[1600px] px-4 pb-24 pt-4 sm:px-6">{children}</main>
          <DemoBar />
        </ThemeProvider>
      </body>
    </html>
  );
}
