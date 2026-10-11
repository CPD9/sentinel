"use client";
// ?theme=light or ?theme=dark switches the theme (and remembers it): handy for the projector and for screenshots.
import { useTheme } from "next-themes";
import { useEffect } from "react";

export function ThemeFromUrl() {
  const { setTheme } = useTheme();
  useEffect(() => {
    const t = new URLSearchParams(window.location.search).get("theme");
    if (t === "light" || t === "dark") setTheme(t);
  }, [setTheme]);
  return null;
}
