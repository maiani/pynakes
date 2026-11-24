/** Desktop engine discovery has no editor settings or Python environment mutation. */
import * as path from "node:path";
import * as fs from "node:fs";
import { engineVersion, type PynakesCommand } from "../../../packages/client-core/src/engine/pynakes";

export async function resolveDesktopEngine(root: string): Promise<PynakesCommand> {
  if (process.env.PYNAKES_EXECUTABLE) {
    const command = { executable: process.env.PYNAKES_EXECUTABLE, leadingArgs: [] };
    if (await engineVersion(command)) return command;
    throw new Error("PYNAKES_EXECUTABLE could not run pynakes. Check the selected executable.");
  }
  const launcher = [path.join(root, "engine/pynakes_launcher.py"),
    path.resolve(root, "../../../clients/vscode/engine/pynakes_launcher.py")].find(file => fs.existsSync(file));
  if (launcher) {
    const candidates = process.env.PYNAKES_PYTHON ? [process.env.PYNAKES_PYTHON] : ["python3", "python"];
    for (const executable of candidates) {
      const command = { executable, leadingArgs: ["-I", "-S", launcher] };
      if (await engineVersion(command)) return command;
    }
  }
  const installed = { executable: "pynakes", leadingArgs: [] };
  if (await engineVersion(installed)) return installed;
  throw new Error("No compatible engine found. Install CPython 3.12–3.15 for the bundled engine, or install pynakes and set PYNAKES_EXECUTABLE to its executable.");
}
