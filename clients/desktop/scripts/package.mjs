import { packager } from "@electron/packager";
import { cp, rm } from "node:fs/promises";
import { execFileSync } from "node:child_process";
execFileSync(process.platform === "win32" ? "npm.cmd" : "npm", ["--prefix", "../vscode", "run", "vendor-engine"], { stdio: "inherit" });
await cp("../../LICENSE", "build/LICENSE");
await cp("../vscode/engine", "build/engine", { recursive: true });
try {
  const outputs = await packager({ dir: ".", name: "Pynakes", out: "dist", overwrite: true,
    asar: false, prune: true,
    ignore: [/^\/src($|\/)/, /^\/test($|\/)/, /^\/scripts($|\/)/, /^\/assets($|\/)/,
      /^\/build\/test($|\/)/, /^\/node_modules($|\/)/, /^\/dist($|\/)/, /^\/tsconfig\.json$/, /^\/package-lock\.json$/],
  });
  console.log(outputs.join("\n"));
} finally { await rm("build/engine", { recursive: true, force: true }); }
