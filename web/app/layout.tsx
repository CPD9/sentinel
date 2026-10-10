import type { Metadata } from "next";
import { ThemeProvider } from "next-themes";
import { TopNav } from "@/components/shell/nav";
import "./globals.css";

export const metadata: Metadata = {
  title: "SENTINEL — call compliance review",
  description: "Self-hosted compliance review of bank phone calls.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <ThemeProvider attribute="class" defaultTheme="dark" enableSystem disableTransitionOnChange>
          <TopNav />
          <main className="mx-auto max-w-[1400px] px-4 py-6">{children}</main>
        </ThemeProvider>
      </body>
    </html>
  );
}
