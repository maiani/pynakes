// @ts-check
/**
 * The detail pane: an entry's fields, editable.
 *
 * Editing stages a change in the extension; nothing is written here. Each edit
 * carries the value it was made against, which is what lets the extension
 * refuse a commit when the file has moved underneath.
 */
window.PV = window.PV || {};

(function (PV) {
  "use strict";

  /** Fields shown first; the rest follow alphabetically. */
  const ORDER = [
    "author", "editor", "title", "subtitle", "shorttitle", "journaltitle", "journal",
    "booktitle", "publisher", "year", "date", "volume", "number", "pages", "doi",
    "url", "eprint", "groups", "file", "abstract",
  ];

  /** Values this long, or with newlines, get a textarea rather than an input. */
  const LONG_VALUE = 70;

  const STAGE_DEBOUNCE_MS = 300;

  let container;
  const timers = new Map();

  PV.detailInit = (element) => {
    container = element;
  };

  /** True while the user is typing in this pane, so a re-render would interrupt. */
  function hasFocus() {
    const active = document.activeElement;
    return Boolean(active && container.contains(active) && active !== container);
  }

  function orderedFields(row) {
    const names = PV.fieldNames(row);
    return ORDER.filter((name) => names.includes(name)).concat(
      names.filter((name) => !ORDER.includes(name)).sort(),
    );
  }

  function stage(key, field, value, base) {
    PV.post({ type: "stageField", key, field, value, base });
  }

  function debouncedStage(key, field, value, base) {
    const id = key + " " + field;
    clearTimeout(timers.get(id));
    timers.set(
      id,
      setTimeout(() => {
        timers.delete(id);
        stage(key, field, value, base);
      }, STAGE_DEBOUNCE_MS),
    );
  }

  /** Which fields get a "Compare with remote" button: `doi` and/or `eprint`, whichever the entry has. */
  function compareTargetFields(row) {
    const names = PV.fieldNames(row);
    return ["doi", "eprint"].filter((name) => names.includes(name));
  }

  function fieldEditor(row, field, showCompare) {
    const base = row.fields[field] ?? null;
    const staged = PV.stagedField(row.key, field);
    const value = PV.effectiveValue(row, field);
    const cleared = Boolean(staged) && staged.value === null;

    const wrapper = document.createElement("div");
    wrapper.className = "field-row" + (staged ? " staged" : "") + (cleared ? " cleared" : "");

    const label = document.createElement("label");
    label.className = "field-name";
    label.textContent = field;
    label.title = staged
      ? cleared
        ? field + " will be removed (was: " + (staged.base ?? "absent") + ")"
        : field + " was: " + (staged.base ?? "absent")
      : field;
    wrapper.appendChild(label);

    if (cleared) {
      const note = document.createElement("span");
      note.className = "field-cleared-note";
      note.textContent = "will be removed";
      wrapper.appendChild(note);
    } else {
      const text = value ?? "";
      const multiline = text.length > LONG_VALUE || text.includes("\n");
      const input = document.createElement(multiline ? "textarea" : "input");
      input.className = "field-value";
      input.value = text;
      input.spellcheck = false;
      if (multiline) {
        input.rows = Math.min(8, Math.max(2, Math.ceil(text.length / LONG_VALUE) + 1));
      } else {
        input.type = "text";
      }
      input.id = "field-" + field;
      label.htmlFor = input.id;
      input.addEventListener("input", () => debouncedStage(row.key, field, input.value, base));
      input.addEventListener("blur", () => {
        clearTimeout(timers.get(row.key + " " + field));
        stage(row.key, field, input.value, base);
      });
      wrapper.appendChild(input);
    }

    const actions = document.createElement("span");
    actions.className = "field-actions";
    if (showCompare) {
      const comparing = PV.state.compareBusy === row.key;
      const compare = document.createElement("button");
      compare.type = "button";
      compare.className = "icon-button";
      compare.textContent = comparing ? "…" : "⇄";
      compare.disabled = comparing;
      compare.title = comparing
        ? "Comparing…"
        : "Compare with remote: fetch DOI/arXiv metadata and compare it field by field";
      compare.addEventListener("click", () => {
        PV.state.compareBusy = row.key;
        PV.renderDetail();
        PV.post({ type: "compareRemote", key: row.key });
      });
      actions.appendChild(compare);
    }
    if (staged) {
      const revert = document.createElement("button");
      revert.type = "button";
      revert.className = "icon-button";
      revert.textContent = "undo";
      revert.title = "Discard this pending change";
      revert.addEventListener("click", () =>
        PV.post({ type: "unstageField", key: row.key, field }),
      );
      actions.appendChild(revert);
    }
    if (!cleared) {
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "icon-button";
      remove.textContent = "remove";
      remove.title = base === null ? "Drop this new field" : "Remove this field from the entry";
      remove.addEventListener("click", () => {
        if (base === null) {
          PV.post({ type: "unstageField", key: row.key, field });
        } else {
          stage(row.key, field, null, base);
        }
      });
      actions.appendChild(remove);
    }
    wrapper.appendChild(actions);
    return wrapper;
  }

  function addFieldRow(row) {
    const form = document.createElement("div");
    form.className = "add-field";

    const name = document.createElement("input");
    name.type = "text";
    name.className = "add-field-name";
    name.placeholder = "field";
    name.spellcheck = false;

    const value = document.createElement("input");
    value.type = "text";
    value.className = "add-field-value";
    value.placeholder = "value";
    value.spellcheck = false;

    const add = document.createElement("button");
    add.type = "button";
    add.className = "button";
    add.textContent = "Add field";
    const submit = () => {
      const field = name.value.trim().toLowerCase();
      if (!field) {
        name.focus();
        return;
      }
      stage(row.key, field, value.value, null);
      name.value = "";
      value.value = "";
      name.focus();
    };
    add.addEventListener("click", submit);
    for (const input of [name, value]) {
      input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          submit();
        }
      });
    }

    form.append(name, value, add);
    return form;
  }

  function header(row) {
    const head = document.createElement("div");
    head.className = "detail-header";

    const renaming = PV.state.renameBusy === row.key;
    const title = document.createElement("input");
    title.type = "text";
    title.className = "detail-key";
    title.value = row.key;
    title.spellcheck = false;
    title.disabled = renaming;
    title.title = "Citation key";
    title.addEventListener("blur", () => {
      const value = title.value.trim();
      if (!value || value === row.key) {
        title.value = row.key;
        return;
      }
      PV.state.renameBusy = row.key;
      PV.renderDetail();
      PV.post({ type: "renameKey", key: row.key, newKey: value });
    });
    title.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        title.blur();
      } else if (event.key === "Escape") {
        event.preventDefault();
        title.value = row.key;
        title.blur();
      }
    });
    head.appendChild(title);

    const typeRow = document.createElement("div");
    typeRow.className = "detail-type-row";
    const at = document.createElement("span");
    at.className = "detail-at";
    at.textContent = "@";
    const stagedType = PV.state.staging.entries?.[row.key]?.entryType;
    const type = document.createElement("input");
    type.type = "text";
    type.className = "detail-type" + (stagedType ? " staged" : "");
    type.value = stagedType ? stagedType.value : row.type;
    type.spellcheck = false;
    type.title = "Entry type";
    type.addEventListener("blur", () =>
      PV.post({ type: "stageType", key: row.key, value: type.value.trim(), base: row.type }),
    );
    typeRow.append(at, type);
    head.appendChild(typeRow);

    const actions = document.createElement("div");
    actions.className = "detail-actions";
    const reveal = document.createElement("button");
    reveal.className = "button";
    reveal.type = "button";
    reveal.textContent = "Show source";
    reveal.addEventListener("click", () => PV.post({ type: "reveal", key: row.key }));
    const copy = document.createElement("button");
    copy.className = "button";
    copy.type = "button";
    copy.textContent = "Copy key";
    copy.addEventListener("click", () => PV.post({ type: "copyKey", key: row.key }));
    actions.append(reveal, copy);
    if (PV.entryStaged(row.key)) {
      const discard = document.createElement("button");
      discard.className = "button";
      discard.type = "button";
      discard.textContent = "Discard entry changes";
      discard.addEventListener("click", () => PV.post({ type: "discardEntry", key: row.key }));
      actions.appendChild(discard);
    }
    head.appendChild(actions);
    return head;
  }

  function membership(row) {
    const groups = PV.state.groupsByEntry?.[row.key] || [];
    const issues = PV.state.lint?.byKey?.[row.key] || [];
    const fragment = document.createDocumentFragment();

    if (groups.length > 0) {
      const section = document.createElement("div");
      section.className = "detail-section";
      const heading = document.createElement("h3");
      heading.textContent = "Groups";
      section.appendChild(heading);
      const list = document.createElement("div");
      list.className = "chips";
      for (const group of groups) {
        const chip = document.createElement("span");
        chip.className = "chip";
        chip.textContent = group;
        list.appendChild(chip);
      }
      section.appendChild(list);
      fragment.appendChild(section);
    }

    if (issues.length > 0) {
      const section = document.createElement("div");
      section.className = "detail-section";
      const heading = document.createElement("h3");
      heading.textContent = "Findings";
      section.appendChild(heading);
      for (const issue of issues) {
        const line = document.createElement("p");
        line.className = "finding finding-" + issue.severity;
        line.textContent = issue.message;
        section.appendChild(line);
      }
      fragment.appendChild(section);
    }
    return fragment;
  }

  PV.renderDetail = (options) => {
    // Re-rendering while a field is focused would move the caret or drop it.
    if (options?.preserveFocus && hasFocus()) {
      return;
    }
    const s = PV.state;
    const row =
      s.visible.find((candidate) => candidate.key === s.selectedKey) ||
      s.rows.find((candidate) => candidate.key === s.selectedKey);
    if (!row) {
      const hint = document.createElement("p");
      hint.className = "hint";
      hint.textContent = "Select an entry to see and edit its fields.";
      container.replaceChildren(hint);
      return;
    }

    const compareFields = compareTargetFields(row);
    const fields = document.createElement("div");
    fields.className = "fields";
    for (const field of orderedFields(row)) {
      fields.appendChild(fieldEditor(row, field, compareFields.includes(field)));
    }

    container.replaceChildren(header(row), fields, addFieldRow(row), membership(row));
  };
})(window.PV);
