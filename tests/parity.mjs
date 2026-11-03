// Usage: node tests/parity.mjs synthetic.json > js_out.json
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
const PEARS = createRequire(import.meta.url)("../app/metrics.js");
const users = JSON.parse(readFileSync(process.argv[2], "utf8"));
const out = {};
for (const [k, u] of Object.entries(users)) out[k] = PEARS.userMetrics(u.ts, u.artists, u.tracks, { utc: true });
process.stdout.write(JSON.stringify(out));
