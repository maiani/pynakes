import { build } from "esbuild";
import { cp, mkdir, readdir, rm } from "node:fs/promises";
await rm("build", { recursive: true, force: true });
await mkdir("build/test", { recursive: true });
const options = { bundle: true, platform: "node", target: "node22", format: "cjs", external: ["electron"], logLevel: "info" };
await build({ ...options, entryPoints: ["src/main.ts"], outfile: "build/main.cjs" });
await build({ ...options, entryPoints: ["src/preload.ts"], outfile: "build/preload.cjs" });
for (const name of await readdir("test")) if (name.endsWith(".test.ts")) {
  await build({ ...options, entryPoints: [`test/${name}`], outfile: `build/test/${name.replace(/\.ts$/, ".cjs")}` });
}
await cp("../../packages/client-ui/assets", "build/ui", { recursive: true });
for (const name of await readdir("assets")) await cp(`assets/${name}`, `build/${name}`);
