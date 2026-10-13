// @ts-check
/** Bibliography-wide metadata and material actions, backed by engine reports. */
window.PV = window.PV || {};

(function (PV) {
  "use strict";

  function hint(target, text) {
    const paragraph = document.createElement("p");
    paragraph.className = "hint";
    paragraph.textContent = text;
    target.appendChild(paragraph);
  }

  function labeled(form, title, control) {
    const label = document.createElement("label");
    label.textContent = title;
    label.appendChild(control);
    form.appendChild(label);
    return control;
  }

  PV.renderMetadata = (target) => {
    const s = PV.state;
    if (!s.metadata) {
      hint(target, "Metadata is unavailable until the bibliography has been read.");
      return;
    }
    hint(target, "Bibliography settings stored in pynakes-meta and jabref-meta blocks. Changes are validated and shown as a diff before you apply them. Use the Groups sidebar to edit the group hierarchy.");
    const list = document.createElement("div");
    list.className = "metadata-list";
    for (const namespace of ["pynakes", "jabref"]) {
      for (const [key, value] of Object.entries(s.metadata[namespace]?.values || {})) {
        const row = document.createElement("div");
        row.className = "metadata-row";
        const edit = PV.button("link-button", `${namespace}: ${key}`, "Edit this metadata block", () => {
          s.metadataDraft = { namespace, key, value, allowUnknown: false };
          PV.renderDocks();
        });
        const preview = document.createElement("code");
        preview.textContent = value;
        row.append(edit, preview);
        list.appendChild(row);
      }
    }
    if (!list.childElementCount) hint(list, "This bibliography has no metadata blocks.");
    target.appendChild(list);
    target.appendChild(PV.button("button", "New metadata", null, () => {
      s.metadataDraft = { namespace: "pynakes", key: "", value: "", allowUnknown: false };
      PV.renderDocks();
    }));
    const draft = s.metadataDraft;
    if (!draft) return;
    const form = document.createElement("form");
    form.className = "metadata-form";
    const namespace = labeled(form, "Namespace", document.createElement("select"));
    for (const name of ["pynakes", "jabref"]) {
      const option = document.createElement("option");
      option.value = name;
      option.textContent = `${name}-meta`;
      namespace.appendChild(option);
    }
    namespace.value = draft.namespace;
    namespace.addEventListener("change", () => { draft.namespace = namespace.value; });
    const key = labeled(form, "Key", document.createElement("input"));
    key.value = draft.key;
    key.required = true;
    const valueHost = document.createElement("div");
    valueHost.className = "metadata-value";
    form.appendChild(valueHost);
    function renderValue() {
      valueHost.replaceChildren();
      const choices = PV.own(s.metadata.valueChoices, draft.key.trim().toLowerCase());
      const finite = Array.isArray(choices) && choices.length > 0;
      const value = labeled(valueHost, "Value", document.createElement(finite ? "select" : "textarea"));
      if (finite) {
        // Keep an existing spelling, invalid value, or empty draft unchanged.
        // Merely opening the editor must never silently choose a replacement.
        if (!choices.includes(draft.value)) {
          const current = document.createElement("option");
          current.value = draft.value;
          current.textContent = draft.value ? `Current value: ${draft.value}` : "Choose a value…";
          value.appendChild(current);
        }
        for (const choice of choices) {
          const option = document.createElement("option");
          option.value = choice;
          option.textContent = choice;
          value.appendChild(option);
        }
      } else {
        value.rows = 5;
        value.spellcheck = false;
      }
      value.value = draft.value;
      value.addEventListener(finite ? "change" : "input", () => { draft.value = value.value; });
    }
    key.addEventListener("input", () => { draft.key = key.value; renderValue(); });
    renderValue();
    const unknown = document.createElement("input");
    unknown.type = "checkbox";
    unknown.checked = draft.allowUnknown;
    labeled(form, "Allow an unrecognized JabRef key", unknown);
    unknown.addEventListener("change", () => { draft.allowUnknown = unknown.checked; });
    const submit = (remove) => {
      if (!draft.key.trim()) { key.reportValidity(); return; }
      PV.post({ type: "mutate", mutation: { kind: "metadata", edit: {
        namespace: draft.namespace, key: draft.key, value: remove ? null : draft.value,
        allowUnknown: draft.allowUnknown,
      } } });
    };
    form.addEventListener("submit", (event) => { event.preventDefault(); submit(false); });
    const save = PV.button("button", "Review change…", null);
    save.type = "submit";
    form.append(save,
      PV.button("button", "Remove block…", "Review removal of this metadata block", () => submit(true)),
      PV.button("button", "Cancel", null, () => { s.metadataDraft = null; PV.renderDocks(); }),
    );
    target.appendChild(form);
  };

  PV.renderMaterials = (target) => {
    const s = PV.state;
    hint(target, "Fetch missing materials for the whole bibliography. To open or fetch one entry's materials, select it and use the Edit pane.");
    const fetch = PV.button("button", s.fetchBusy !== null ? "Fetching…" : "Fetch missing materials…", null, () => {
      s.fetchBusy = "*";
      PV.renderDocks();
      PV.post({ type: "fetchMaterials" });
    });
    fetch.id = "fetch-materials";
    fetch.disabled = s.fetchBusy !== null;
    target.appendChild(fetch);
    if (!s.materials) {
      hint(target, "Material information is unavailable.");
      return;
    }
    const materials = Object.values(s.materials.byKey || {}).flat();
    hint(target, `${materials.filter((material) => material.present).length} available materials; ${materials.filter((material) => !material.present).length} missing or unresolved.`);
    if (s.materials.pinaxRoot) hint(target, `Pinax folder: ${s.materials.pinaxRoot}`);
  };
})(window.PV);
