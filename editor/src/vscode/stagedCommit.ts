/** VS Code document, mirror and dialog adapter for the shared edit session. */
import * as path from "node:path";
import * as vscode from "vscode";
import { resolveEngine } from "./engineDiscovery";
import { commitEdits, previewEdits, type PreviewResult } from "../core/library";
import type { SessionHost } from "../core/session";
import type { MutationHost } from "./mutations";

export interface StagingHost extends MutationHost {
  postStaging(): void;
}

export function sessionHost(host: StagingHost): SessionHost {
  return {
    post: message => host.post(message),
    postStaging: () => host.postStaging(),
    reload: () => host.reload(),
    describeFailure: error => host.describeFailure(error),
    preview: async requests => {
      let result: PreviewResult | undefined;
      await host.withMirror(async ({ command, cwd, source }) => {
        result = await previewEdits(command, source, requests, cwd);
      }, error => {
        // Let the session publish this result only if the preview is still current.
        result = { ok: false, conflict: false, message: String(error.message ?? "the engine could not run") };
        return undefined;
      });
      if (!result) throw new Error("The engine returned no preview.");
      return result;
    },
    prepareWrite: async () => {
      const { document } = host;
      if (document.uri.scheme !== "file") {
        return { error: "This document is not a local file, so it cannot be written." };
      }
      if (!(await host.reconcileBuffer())) {
        return { error: "Apply cancelled: the file still has unsaved changes." };
      }
      const { command } = await resolveEngine(document.uri);
      const cwd = host.workingDirectory();
      const source = document.uri.fsPath;
      return {
        name: path.basename(source),
        preview: requests => previewEdits(command, source, requests, cwd),
        commit: (requests, digest) => commitEdits(command, source, requests, digest, cwd),
      };
    },
    approve: async ({ name, counts }) => {
      const answer = await vscode.window.showWarningMessage(
        `Apply ${counts.fields} ${counts.fields === 1 ? "change" : "changes"} to ` +
          `${counts.entries} ${counts.entries === 1 ? "entry" : "entries"} in ${name}?`,
        { modal: true, detail: "The exact diff is shown in the bibliography view." },
        "Apply",
      );
      return answer === "Apply";
    },
  };
}
