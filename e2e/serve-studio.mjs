import http from "node:http";
import fs from "node:fs";
import path from "node:path";

const root = path.resolve("apps/studio/dist");
const port = 10087;

http
  .createServer((req, res) => {
    const url = (req.url || "/").split("?")[0];
    const rel = url.startsWith("/studio") ? url.slice("/studio".length) || "/" : url;
    let file = path.join(root, rel === "/" ? "index.html" : rel);
    if (!file.startsWith(root) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
      file = path.join(root, "index.html");
    }
    const ext = path.extname(file);
    const types = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml" };
    res.setHeader("Content-Type", types[ext] || "application/octet-stream");
    fs.createReadStream(file).pipe(res);
  })
  .listen(port, () => {
    console.log(`studio e2e http://127.0.0.1:${port}/studio/`);
  });
