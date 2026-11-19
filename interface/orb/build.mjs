// Builds the orb into ../static/ (orb.js, orb-gestures.js, orb.css). Run: npm install && npm run build
import { build } from "esbuild";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const out = path.join(here, "..", "static");
const common = { bundle: true, minify: true, format: "iife", target: "es2020", legalComments: "none", logLevel: "info" };

// Scene + HUD (three.js). Loaded with the dashboard.
await build({ ...common, entryPoints: [path.join(here, "src", "entry.ts")], outfile: path.join(out, "orb.js") });
// Hand tracking (MediaPipe JS). Loaded only when gestures are switched on.
await build({ ...common, entryPoints: [path.join(here, "src", "gestures.ts")], outfile: path.join(out, "orb-gestures.js") });
await build({ bundle: true, minify: true, entryPoints: [path.join(here, "src", "orb.css")], outfile: path.join(out, "orb.css"), logLevel: "info" });
