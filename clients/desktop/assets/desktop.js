/* Desktop-only controls; the bibliography UI itself is shared with VS Code. */
(() => {
  const host = window.PynakesHost;
  const dialog = document.createElement("dialog");
  dialog.className = "desktop-prompt";
  const form = document.createElement("form");
  form.method = "dialog";
  dialog.append(form);
  document.body.append(dialog);
  let request;
  host.onMessage(message => {
    if (message.type !== "desktopPrompt") return;
    request = message.id;
    form.replaceChildren();
    const title = document.createElement("h2");
    title.textContent = message.title;
    form.append(title);
    for (const field of message.fields) {
      const label = document.createElement("label");
      label.textContent = field.label;
      const input = document.createElement(field.choices?.length ? "select" : "input");
      input.name = field.name;
      input.required = Boolean(field.required);
      if (field.choices?.length) for (const choice of field.choices) {
        const option = document.createElement("option");
        option.value = choice;
        option.textContent = choice;
        input.append(option);
      }
      if (field.value) input.value = field.value;
      label.append(input);
      form.append(label);
    }
    const actions = document.createElement("div");
    actions.className = "desktop-prompt-actions";
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.textContent = "Cancel";
    cancel.addEventListener("click", () => dialog.close("cancel"));
    const submit = document.createElement("button");
    submit.type = "submit";
    submit.value = "continue";
    submit.textContent = "Continue";
    actions.append(cancel, submit);
    form.append(actions);
    dialog.returnValue = "cancel";
    dialog.showModal();
  });
  dialog.addEventListener("close", () => {
    if (!request) return;
    host.postMessage({ type: "desktopPromptResult", id: request,
      values: dialog.returnValue === "continue" ? Object.fromEntries(new FormData(form)) : null });
    request = undefined;
  });
  const open = document.createElement("button");
  open.className = "button";
  open.type = "button";
  open.textContent = "Open…";
  open.title = "Open another bibliography in a new window";
  open.addEventListener("click", () => host.postMessage({ type: "desktopOpen" }));
  document.querySelector(".toolbar").prepend(open);
})();
