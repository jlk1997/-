import { createHash } from "node:crypto";
import { readdirSync, readFileSync, renameSync, writeFileSync, existsSync } from "node:fs";
import { join } from "node:path";

const dist = join(process.cwd(), "dist-h5");
const cssDir = join(dist, "css");
if (!existsSync(cssDir)) process.exit(0);

const hashed = /\.[0-9a-f]{8}\.css$/i;
const files = readdirSync(cssDir).filter((name) => name.endsWith(".css") && !hashed.test(name));
if (!files.length) process.exit(0);

const replacements = [];
for (const file of files) {
  const src = join(cssDir, file);
  const digest = createHash("md5").update(readFileSync(src)).digest("hex").slice(0, 8);
  const next = file.replace(/\.css$/i, `.${digest}.css`);
  renameSync(src, join(cssDir, next));
  replacements.push([file, next]);
}

const rewrite = (text) => replacements.reduce((acc, [from, to]) => acc.split(from).join(to), text);

const htmlPath = join(dist, "index.html");
if (existsSync(htmlPath)) writeFileSync(htmlPath, rewrite(readFileSync(htmlPath, "utf8")));

const jsDir = join(dist, "js");
if (existsSync(jsDir)) {
  for (const name of readdirSync(jsDir).filter((file) => file.endsWith(".js"))) {
    const path = join(jsDir, name);
    const next = rewrite(readFileSync(path, "utf8"));
    writeFileSync(path, next);
  }
}
