import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const baselinePath = path.join(root, "scripts", "style-token-baseline.json");
const update = process.argv.includes("--update");
const hex = /#[0-9a-fA-F]{3,8}\b/;
const px = /(?<![\w-])\d+px\b/;

function walk(dir, out) {
  for (const name of fs.readdirSync(dir)) {
    const full = path.join(dir, name);
    if (name === "node_modules" || name === "dist-h5") continue;
    const stat = fs.statSync(full);
    if (stat.isDirectory()) walk(full, out);
    else if (/\.(scss|css|tsx|ts)$/.test(name)) out.push(full);
  }
}

const files = [];
walk(path.join(root, "apps", "client", "src"), files);
const counts = {};
for (const file of files) {
  const lines = fs.readFileSync(file, "utf8").split(/\r?\n/);
  let inMedia = false;
  let depth = 0;
  let mediaDepth = -1;
  let n = 0;
  for (const line of lines) {
    if (line.includes("@media")) {
      inMedia = true;
      mediaDepth = depth;
    }
    if (hex.test(line)) n += 1;
    if (!inMedia && px.test(line)) n += 1;
    const open = (line.match(/\{/g) || []).length;
    const close = (line.match(/\}/g) || []).length;
    depth += open - close;
    if (inMedia && depth <= mediaDepth) inMedia = false;
  }
  if (n) counts[path.relative(root, file).replaceAll("\\", "/")] = n;
}

if (update) {
  fs.writeFileSync(baselinePath, JSON.stringify(counts, null, 2) + "\n");
  console.log(`wrote ${Object.keys(counts).length} files`);
  process.exit(0);
}

const baseline = fs.existsSync(baselinePath) ? JSON.parse(fs.readFileSync(baselinePath, "utf8")) : {};
const problems = [];
for (const [file, count] of Object.entries(counts)) {
  const allowed = baseline[file] || 0;
  if (count > allowed) problems.push(`${file} has ${count} hardcoded colors or px, baseline ${allowed}`);
}
if (problems.length) {
  console.error(problems.slice(0, 30).join("\n"));
  process.exit(1);
}
console.log("style-token-lint ok");
