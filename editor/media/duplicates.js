// @ts-check
/**
 * The Duplicates pane: the clusters `dedupe check` reports, each with the
 * merge that resolves it. Every key is a real button, so a keyboard user can
 * select an entry from here exactly as a pointer user can.
 */
window.PV = window.PV || {};

(function (PV) {
  "use strict";

  /**
   * Duplicate clusters, each with the merge that would resolve it.
   *
   * Merging is offered per cluster rather than for the file, because deciding
   * that two records are the same work is a judgement made one pair at a time.
   * The engine's `dedupe merge --key` is what makes that possible; without it
   * the only choice would be every merge or none.
   */
  PV.renderDuplicates = (target) => {
    const duplicates = PV.state.duplicates;
    if (duplicates === null) {
      const hint = document.createElement("p");
      hint.className = "hint";
      hint.textContent = "Choose Duplicates in the toolbar to look for repeated works.";
      target.appendChild(hint);
      return;
    }
    if (duplicates === "loading") {
      const hint = document.createElement("p");
      hint.className = "hint";
      hint.textContent = "Looking for duplicates…";
      target.appendChild(hint);
      return;
    }
    if (!Array.isArray(duplicates)) {
      const problem = document.createElement("p");
      problem.className = "hint";
      problem.textContent = duplicates.error;
      target.appendChild(problem);
      return;
    }
    if (duplicates.length === 0) {
      const hint = document.createElement("p");
      hint.className = "hint";
      hint.textContent = "No duplicate works found.";
      target.appendChild(hint);
      return;
    }

    for (const cluster of duplicates) {
      const section = document.createElement("div");
      section.className = "dup-cluster";

      const head = document.createElement("div");
      head.className = "dup-head";
      const reason = document.createElement("span");
      reason.className = "dup-reason";
      reason.textContent = cluster.reason;
      head.appendChild(reason);
      const identity = document.createElement("span");
      identity.className = "dup-identity";
      identity.textContent = cluster.identity?.value || "matched by title";
      head.appendChild(identity);
      section.appendChild(head);

      for (const [index, entry] of (cluster.entries || []).entries()) {
        const line = document.createElement("div");
        line.className = "dup-entry";
        const key = PV.button("link-button dup-key", entry.key, "Select this entry", () =>
          PV.select(entry.key),
        );
        line.appendChild(key);
        const title = document.createElement("span");
        title.className = "dup-title";
        title.textContent = entry.fields?.title || "";
        line.appendChild(title);
        if (index === 0) {
          const survivor = document.createElement("span");
          survivor.className = "dup-survivor";
          survivor.textContent = "keeps";
          line.appendChild(survivor);
        }
        section.appendChild(line);
      }

      const merge = PV.button(
        "button",
        "Merge this pair",
        "Fold the copies into the first entry, after reviewing the diff",
        () => {
          PV.post({
            type: "mutate",
            // The cluster is named by a key inside it, so the engine re-finds it
            // rather than the view describing a merge it cannot perform.
            mutation: { kind: "dedupeMerge", keys: cluster.keys },
          });
        },
      );
      section.appendChild(merge);
      target.appendChild(section);
    }
  };
})(window.PV);
