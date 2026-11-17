import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const files = [
  "packages/i18n/src/locales/zh.ts",
  "packages/i18n/src/locales/en.ts",
];
const forbidden = ["完成带", "抄账", "Demucs", "农场", "tracks=1", "Work B", "席位"];

function walk(dir, out) {
  for (const name of fs.readdirSync(dir)) {
    const full = path.join(dir, name);
    const stat = fs.statSync(full);
    if (stat.isDirectory()) {
      if (name === "node_modules") continue;
      walk(full, out);
    } else if (/\.(ts|tsx)$/.test(name) && !full.endsWith(`${path.sep}legal-documents.ts`)) {
      out.push(full);
    }
  }
}

const targets = files.map((file) => path.join(root, file));
walk(path.join(root, "apps", "client", "src"), targets);

const hits = [];
for (const file of targets) {
  const text = fs.readFileSync(file, "utf8");
  const lines = text.split(/\r?\n/);
  lines.forEach((line, index) => {
    for (const word of forbidden) {
      if (line.includes(word)) hits.push(`${path.relative(root, file)}:${index + 1} ${word}`);
    }
  });
}

if (hits.length) {
  console.error(hits.slice(0, 40).join("\n"));
  console.error(`copy-lint failed: ${hits.length}`);
  process.exit(1);
}
console.log("copy-lint ok");
