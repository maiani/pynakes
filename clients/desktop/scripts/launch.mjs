import { spawn } from "node:child_process";
import electron from "electron";
const env = { ...process.env };
// Coding hosts can export this flag; the desktop must start as an application.
delete env.ELECTRON_RUN_AS_NODE;
const child = spawn(electron, [".", ...process.argv.slice(2)], { stdio: "inherit", env });
child.on("error", error => { console.error(error); process.exitCode = 1; });
child.on("exit", code => { process.exitCode = code ?? 1; });
