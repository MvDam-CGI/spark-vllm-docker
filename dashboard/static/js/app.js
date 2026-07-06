import { apiGet } from "./api.js";
import { byId, pages, refreshMs, registerServiceWorker, replaceChildren, requests, setText, state, tokenKey } from "./core.js";
import {
  applyRecipeDefaults,
  launchRuntime,
  refreshLogs,
  renderLaunchOptions,
  renderLogsOptions,
  renderOverview,
  renderRecipes,
  renderRuntime,
  renderSettings,
  setRefreshAllHook,
  showLaunchTab,
  updateCommandPreview,
} from "./views.js";

setRefreshAllHook(refreshAll);

document.addEventListener("DOMContentLoaded", () => {
  bindNavigation();
  bindForms();
  renderAll();
  registerServiceWorker();
  refreshAll();
  setInterval(refreshAll, refreshMs);
});

function bindNavigation() {
  window.addEventListener("hashchange", showRoute);
  showRoute();
}

function showRoute() {
  const page = pages.includes(location.hash.slice(1)) ? location.hash.slice(1) : "overview";
  document.querySelectorAll("[data-page]").forEach((section) => {
    section.classList.toggle("is-active", section.dataset.page === page);
  });
  document.querySelectorAll("[data-page-link]").forEach((link) => {
    link.toggleAttribute("aria-current", link.dataset.pageLink === page);
  });
  document.title = page === "runtime" ? "Monitoring" : page[0].toUpperCase() + page.slice(1);
}

function bindForms() {
  document.addEventListener("toggle", rememberDetailsState, true);
  document.querySelectorAll("input[name='recipe-filter']").forEach((input) => {
    input.addEventListener("change", renderRecipes);
  });
  byId("launch-recipe").addEventListener("change", applyRecipeDefaults);
  byId("launch-form").addEventListener("input", updateCommandPreview);
  byId("launch-form").addEventListener("submit", launchRuntime);
  document.querySelectorAll("[data-launch-tab]").forEach((button) => {
    button.addEventListener("click", () => showLaunchTab(button.dataset.launchTab));
  });
  byId("token-form").addEventListener("submit", (event) => {
    event.preventDefault();
    sessionStorage.setItem(tokenKey, byId("control-token").value);
    setText("token-status", "Control token saved for this tab.");
  });
  byId("refresh-logs").addEventListener("click", refreshLogs);
  byId("copy-logs").addEventListener("click", () => navigator.clipboard.writeText(byId("raw-logs").textContent));
  byId("logs-runtime").addEventListener("change", refreshLogs);
}

function rememberDetailsState(event) {
  const details = event.target;
  if (!(details instanceof HTMLDetailsElement) || !details.dataset.detailKey) return;
  if (details.open) state.openDetails.add(details.dataset.detailKey);
  else state.openDetails.delete(details.dataset.detailKey);
}

async function refreshAll() {
  const settled = await Promise.allSettled(requests.map(([, path]) => apiGet(path)));
  state.failures.clear();
  settled.forEach((result, index) => {
    const [key] = requests[index];
    if (result.status === "fulfilled") {
      applyResult(key, result.value);
    } else {
      state.failures.set(key, result.reason.message || "Unavailable");
    }
  });
  renderAll();
}

function applyResult(key, value) {
  if (key === "recipes") state.recipes = value.recipes || [];
  if (key === "runtimes") state.runtimes = value.runtimes || [];
  if (key === "gpu") state.gpu = value;
  if (key === "system") state.system = value;
  if (key === "settings") state.settings = value;
}

function renderAll() {
  const failing = state.failures.size;
  setText("connection-state", failing ? `Partial telemetry: ${failing} check${failing === 1 ? "" : "s"} unavailable` : "Live");
  document.querySelectorAll("[data-control-action]").forEach((button) => {
    button.disabled = failing === requests.length;
  });
  renderOverview();
  renderRecipes();
  renderRuntime();
  renderLaunchOptions();
  renderLogsOptions();
  renderSettings();
}
