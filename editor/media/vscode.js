/* The only browser script allowed to know about the VS Code webview API. */
(() => {
  const api = acquireVsCodeApi();
  window.PynakesHost = Object.freeze({
    postMessage: message => api.postMessage(message),
    getState: () => api.getState(),
    setState: state => api.setState(state),
    onMessage: handler => {
      const listener = event => handler(event.data);
      window.addEventListener("message", listener);
      return () => window.removeEventListener("message", listener);
    },
  });
})();
