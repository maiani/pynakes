import { cp, rm } from "node:fs/promises";
import { watch } from "node:fs";
import { spawn } from "node:child_process";
const assets = "../../packages/client-ui/assets";
await rm("out", { recursive: true, force: true });
await cp(assets, "out/ui", { recursive: true });
if (process.argv.includes("--watch")) {
  // Assets are flat; serialize refreshes so rapid saves cannot race a copy.
  let pending = Promise.resolve();
  const watcher = watch(assets, () => {
    pending = pending.then(async () => {
      await rm("out/ui", { recursive: true, force: true });
      await cp(assets, "out/ui", { recursive: true });
    }).catch(error => { console.error(error); process.exitCode = 1; });
  });
  const child = spawn(process.execPath, ["node_modules/typescript/bin/tsc", "-p", ".", "--watch"], { stdio: "inherit" });
  child.on("exit", code => { watcher.close(); process.exitCode = code ?? 1; });
  for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => { watcher.close(); child.kill(signal); });
}
