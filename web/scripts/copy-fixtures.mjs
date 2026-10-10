// Copies ../fixtures/*.json into public/fixtures so fixtures mode can fetch them. MOCK data only.
import { cpSync, existsSync, mkdirSync, readdirSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const src = join(root, "..", "fixtures");
const dst = join(root, "public", "fixtures");
if (!existsSync(src)) {
  console.warn(`[copy-fixtures] ${src} not found; fixtures mode will show empty states`);
  process.exit(0);
}
rmSync(dst, { recursive: true, force: true });
mkdirSync(dst, { recursive: true });
let n = 0;
for (const f of readdirSync(src)) {
  if (f.endsWith(".json")) { cpSync(join(src, f), join(dst, f)); n++; }
}
console.log(`[copy-fixtures] copied ${n} files to public/fixtures`);
