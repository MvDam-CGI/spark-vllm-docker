export const state = {
  recipes: [],
  runtimes: [],
  gpu: null,
  system: null,
  settings: null,
  failures: new Map(),
  openDetails: new Set(),
  launchLogTimer: null,
};

export const pages = ["overview", "recipes", "runtime", "launch", "logs", "settings"];
export const tokenKey = "spark-dashboard-token";
export const refreshMs = 5000;

export const requests = [
  ["recipes", "/api/recipes"],
  ["runtimes", "/api/runtimes"],
  ["gpu", "/api/gpu"],
  ["system", "/api/system"],
  ["settings", "/api/settings"],
];

export function currentControlToken() {
  return byId("control-token").value || sessionStorage.getItem(tokenKey) || "";
}

export function registerServiceWorker() {
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js");
}

export function detailsElement(key, summaryText) {
  const details = document.createElement("details");
  details.dataset.detailKey = key;
  details.open = state.openDetails.has(key);
  details.append(el("summary", "", summaryText));
  return details;
}

export function emptyState(title, detail, actionLabel = "", href = "") {
  const node = el("div", "empty-state");
  node.append(el("strong", "", title), el("p", "muted", detail));
  if (actionLabel && href) {
    const action = el("a", "secondary-link", actionLabel);
    action.href = href;
    node.append(action);
  }
  return node;
}

export function meta(label, value) {
  const p = el("p", "recipe-meta");
  p.append(el("strong", "", `${label}: `), textNode(String(value)));
  return p;
}

export function option(value, label) {
  const node = document.createElement("option");
  node.value = value;
  node.textContent = label;
  return node;
}

export function labelize(key) {
  return key.replace(/([A-Z])/g, " $1").replace(/^./, (letter) => letter.toUpperCase());
}

export function byId(id) {
  return document.getElementById(id);
}

export function setText(id, text) {
  byId(id).textContent = text;
}

export function el(tag, className = "", text = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}

export function textNode(text) {
  return document.createTextNode(text);
}

export function replaceChildren(parent, children) {
  parent.replaceChildren(...children);
}
