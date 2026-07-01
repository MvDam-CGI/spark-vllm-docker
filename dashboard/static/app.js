const state = {
  recipes: [],
  runtimes: [],
  gpu: null,
  system: null,
  settings: null,
  failures: new Map(),
};

const pages = ["overview", "recipes", "runtime", "launch", "logs", "settings"];
const tokenKey = "spark-dashboard-token";
const refreshMs = 5000;

const requests = [
  ["recipes", "/api/recipes"],
  ["runtimes", "/api/runtimes"],
  ["gpu", "/api/gpu"],
  ["system", "/api/system"],
  ["settings", "/api/settings"],
];

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
  document.title = page[0].toUpperCase() + page.slice(1);
}

function bindForms() {
  document.querySelectorAll("input[name='recipe-filter']").forEach((input) => {
    input.addEventListener("change", renderRecipes);
  });
  byId("launch-recipe").addEventListener("change", applyRecipeDefaults);
  byId("launch-form").addEventListener("input", updateCommandPreview);
  byId("launch-form").addEventListener("submit", launchRuntime);
  byId("token-form").addEventListener("submit", (event) => {
    event.preventDefault();
    sessionStorage.setItem(tokenKey, byId("control-token").value);
    setText("token-status", "Control token saved for this tab.");
  });
  byId("refresh-logs").addEventListener("click", refreshLogs);
  byId("copy-logs").addEventListener("click", () => navigator.clipboard.writeText(byId("raw-logs").textContent));
  byId("logs-runtime").addEventListener("change", refreshLogs);
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

function renderOverview() {
  const running = state.runtimes.filter((runtime) => runtime.status === "Running").length;
  setText("running-count-badge", running ? `${running} running` : "Nothing running");
  renderOverviewRuntimes();
  renderCapacityPanel();
  replaceChildren(byId("capabilities"), capabilityCards());
  replaceChildren(byId("recent-events"), recentEvents());
}

function renderOverviewRuntimes() {
  const running = state.runtimes.filter((runtime) => runtime.status === "Running");
  const visible = running.length ? running : state.runtimes;
  const nodes = visible.length
    ? visible.map((runtime) => runtimeCard(runtime, { compact: true }))
    : [emptyState("No models are running", "The Spark is idle. Use Launch to dry run a recipe and then start a model when capacity is available.", "Start a model", "#launch")];
  replaceChildren(byId("overview-runtimes"), nodes);
}

function renderCapacityPanel() {
  const gpu = state.gpu?.gpus?.[0];
  const memory = state.system?.memory;
  const disk = state.system?.disk;
  const activePorts = state.runtimes.map((runtime) => runtime.port).filter(Boolean).join(", ") || "None";
  const healthy = state.runtimes.filter((runtime) => runtime.health?.healthy).length;
  const rows = [
    meterRow("GPU memory", gpu ? gpu.memoryPercent : null, gpu ? `${gpu.memoryUsedMiB} MiB used` : gpuUnavailableText()),
    meterRow("System memory", memory ? memory.usedPercent : null, memory ? `${memory.usedMiB} MiB used` : telemetryLabel("system")),
    meterRow("Disk", disk ? disk.usedPercent : null, disk ? `${disk.freeGiB} GiB free` : telemetryLabel("system")),
    summaryRow("Recipes", state.recipes.length || "Loading"),
    summaryRow("Active ports", activePorts),
    summaryRow("Healthy endpoints", healthy),
  ];
  replaceChildren(byId("capacity-panel"), rows);
}

function meterRow(label, percent, detail) {
  const row = el("div", "capacity-row");
  const top = el("div", "capacity-row-top");
  top.append(el("span", "", label), el("strong", "", percent === null ? "Unavailable" : `${percent}%`));
  const meter = document.createElement("meter");
  meter.min = 0;
  meter.max = 100;
  meter.value = percent === null ? 0 : percent;
  row.append(top, meter, el("p", "muted", detail));
  return row;
}

function summaryRow(label, value) {
  const row = el("div", "summary-row");
  row.append(el("span", "", label), el("strong", "", String(value)));
  return row;
}

function capabilityCards() {
  if (!state.recipes.length) {
    return [emptyState("Loading capability map", "Recipe metadata will appear as soon as the backend responds.")];
  }
  const solo = state.recipes.filter((recipe) => !recipe.clusterOnly).length;
  const cluster = state.recipes.filter((recipe) => !recipe.soloOnly).length;
  return [
    infoCard("Solo demos", solo, "Recipes that can run on one Spark"),
    infoCard("Cluster demos", cluster, "Recipes that can use multiple Sparks"),
    infoCard("TranslateGemma", hasRecipe("translategemma-4b-it") ? "Ready" : "Missing", "Solo launch target for port 8001"),
  ];
}

function recentEvents() {
  if (!state.runtimes.length) {
    return [emptyState("No launch events yet", "Start with a dry run from Launch. Events will appear here after the first dashboard action.")];
  }
  return state.runtimes.slice(-6).reverse().map((runtime) => {
    const item = el("li", "event-item");
    item.append(statusPill(runtime.status), textNode(` ${runtime.recipeName} on port ${runtime.port}`));
    return item;
  });
}

function infoCard(label, value, detail) {
  const card = el("article", "info-card");
  card.append(el("p", "metric-label", label), el("div", "metric-value", String(value)), el("p", "muted", detail));
  return card;
}

function renderRecipes() {
  const filter = document.querySelector("input[name='recipe-filter']:checked")?.value || "all";
  const runningSlugs = new Set(state.runtimes.filter((runtime) => runtime.status === "Running").map((runtime) => runtime.recipeSlug));
  const recipes = state.recipes.filter((recipe) => {
    if (filter === "solo") return !recipe.clusterOnly;
    if (filter === "cluster") return !recipe.soloOnly;
    if (filter === "running") return runningSlugs.has(recipe.slug);
    if (filter === "ready") return !runningSlugs.has(recipe.slug);
    return true;
  });
  const nodes = recipes.length ? recipes.map(recipeCard) : [emptyState("No recipes match this view", "Try All, Solo, or Ready to Launch.")];
  replaceChildren(byId("recipe-list"), nodes);
}

function recipeCard(recipe) {
  const card = el("article", "recipe-card");
  const launch = el("button", "primary-button", "Launch");
  launch.type = "button";
  launch.dataset.controlAction = "launch";
  launch.addEventListener("click", () => {
    location.hash = "launch";
    byId("launch-recipe").value = recipe.slug;
    applyRecipeDefaults();
  });
  const details = document.createElement("details");
  details.append(el("summary", "", "Recipe details"));
  details.append(
    meta("Model ID", recipe.model || "Not specified"),
    meta("Container", recipe.container),
    meta("Default port", recipe.defaultPort),
    meta("GPU target", recipe.defaultGpuMemoryUtilization),
    meta("Max model length", recipe.defaultMaxModelLen),
    meta("Mods", recipe.mods.length ? recipe.mods.join(", ") : "None"),
  );
  card.append(
    el("h2", "", recipe.name),
    el("p", "muted", recipe.description || "No description provided."),
    meta("Support", recipe.support),
    details,
    launch,
  );
  return card;
}

function renderRuntime() {
  const nodes = state.runtimes.length ? state.runtimes.map((runtime) => runtimeCard(runtime)) : [emptyState("No runtime selected", "Dashboard-launched runtimes will appear here with health, port, and log actions.")];
  replaceChildren(byId("runtime-list"), nodes);
}

function runtimeCard(runtime, options = {}) {
  const card = el("article", options.compact ? "runtime-card runtime-card-compact" : "runtime-card");
  const actions = el("div", "card-actions");
  const stop = el("button", "danger-button", "Stop");
  stop.type = "button";
  stop.dataset.controlAction = "stop";
  stop.addEventListener("click", () => stopRuntime(runtime.id));
  const logs = el("button", "secondary-button", "Logs");
  logs.type = "button";
  logs.addEventListener("click", () => {
    location.hash = "logs";
    byId("logs-runtime").value = runtime.id;
    refreshLogs();
  });
  actions.append(logs, stop);
  const details = document.createElement("details");
  details.append(el("summary", "", "More runtime details"));
  details.append(
    meta("Runtime name", runtime.id),
    meta("API base URL", `http://127.0.0.1:${runtime.port}/v1`),
    meta("Container name", runtime.containerName || "Unknown"),
    meta("Last health check", runtime.health?.healthy ? "Ready" : "Needs Attention"),
  );
  card.append(
    el("h2", "", runtime.recipeName),
    statusPill(runtime.status),
    meta("Port", runtime.port),
    meta("Mode", runtime.mode || "Unknown"),
    details,
    actions,
  );
  return card;
}

function renderLaunchOptions() {
  const select = byId("launch-recipe");
  const selected = select.value || "translategemma-4b-it";
  replaceChildren(select, state.recipes.map((recipe) => option(recipe.slug, recipe.name)));
  select.value = hasRecipe(selected) ? selected : state.recipes[0]?.slug || "";
  byId("launch-form").classList.toggle("is-disabled", !state.recipes.length);
  if (!byId("launch-port").value && state.recipes.length) applyRecipeDefaults();
  updateCommandPreview();
}

function applyRecipeDefaults() {
  const recipe = selectedRecipe();
  if (!recipe) return;
  byId("launch-port").value = recipe.slug === "translategemma-4b-it" ? 8001 : recipe.defaultPort;
  byId("launch-host").value = recipe.defaultHost;
  byId("launch-gpu-memory").value = recipe.defaultGpuMemoryUtilization;
  byId("launch-max-len").value = recipe.defaultMaxModelLen;
  setText("selected-recipe-summary", `${recipe.name}. ${recipe.description || "No description provided."}`);
  updateCommandPreview();
}

function updateCommandPreview() {
  const payload = launchPayload();
  if (!payload.recipeSlug) {
    setText("command-preview", "Waiting for recipes...");
    return;
  }
  const args = ["./run-recipe.sh", payload.recipeSlug, payload.mode === "solo" ? "--solo" : "--no-ray", "--port", payload.port || "", "--host", payload.host || ""];
  args.push("--gpu-mem", payload.gpuMemoryUtilization || "", "--max-model-len", payload.maxModelLen || "", "--tp", payload.tensorParallel || "1");
  args.push("--name", `vllm-${payload.recipeSlug}-${payload.port || "port"}`);
  if (payload.setup) args.push("--setup");
  if (payload.dryRun) args.push("--dry-run");
  setText("gpu-memory-output", payload.gpuMemoryUtilization || "");
  setText("command-preview", args.join(" "));
}

async function launchRuntime(event) {
  event.preventDefault();
  setText("launch-output", "Submitting launch request...");
  try {
    const result = await apiPost("/api/runtimes", launchPayload());
    setText("launch-output", result.output || `${result.status}. Launch ID: ${result.launchId}`);
    await refreshAll();
  } catch (error) {
    setText("launch-output", error.message);
  }
}

async function stopRuntime(runtimeId) {
  const dialog = byId("confirm-dialog");
  dialog.showModal();
  const confirmed = await new Promise((resolve) => {
    dialog.addEventListener("close", () => resolve(dialog.returnValue === "confirm"), { once: true });
  });
  if (!confirmed) return;
  await apiPost(`/api/runtimes/${runtimeId}/stop`, {});
  await refreshAll();
}

function renderLogsOptions() {
  const select = byId("logs-runtime");
  const selected = select.value;
  replaceChildren(select, state.runtimes.map((runtime) => option(runtime.id, `${runtime.recipeName} : ${runtime.port}`)));
  select.value = state.runtimes.some((runtime) => runtime.id === selected) ? selected : state.runtimes[0]?.id || "";
  if (!state.runtimes.length) {
    setText("raw-logs", "No runtime logs yet. Launch a runtime or dry run first.");
  }
}

async function refreshLogs() {
  const runtimeId = byId("logs-runtime").value;
  if (!runtimeId) return;
  const result = await apiGet(`/api/logs/${runtimeId}?lines=300`);
  setText("raw-logs", result.logs || "No log output returned.");
  replaceChildren(byId("critical-log-events"), (result.events || []).map((event) => el("p", "event-item", `${event.status}: ${event.message}`)));
}

function renderSettings() {
  const settings = state.settings || {};
  const entries = Object.entries(settings);
  const list = byId("settings-list");
  replaceChildren(list, entries.length ? entries.flatMap(([key, value]) => [el("dt", "", labelize(key)), el("dd", "", String(value))]) : [el("dt", "", "Status"), el("dd", "", "Settings are loading.")]);
}

function launchPayload() {
  const data = new FormData(byId("launch-form"));
  return {
    recipeSlug: data.get("recipeSlug"),
    mode: data.get("mode"),
    port: Number(data.get("port")),
    host: data.get("host"),
    gpuMemoryUtilization: Number(data.get("gpuMemoryUtilization")),
    maxModelLen: Number(data.get("maxModelLen")),
    tensorParallel: Number(data.get("tensorParallel") || 1),
    setup: byId("launch-setup").checked,
    dryRun: byId("launch-dry-run").checked,
  };
}

async function apiGet(path) {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  return readJson(response);
}

async function apiPost(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "X-Dashboard-Token": sessionStorage.getItem(tokenKey) || byId("control-token").value,
    },
    body: JSON.stringify(payload),
  });
  return readJson(response);
}

async function readJson(response) {
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Request failed.");
  return data;
}

function selectedRecipe() {
  return state.recipes.find((recipe) => recipe.slug === byId("launch-recipe").value);
}

function hasRecipe(slug) {
  return state.recipes.some((recipe) => recipe.slug === slug);
}

function statusPill(status) {
  const text = status || "Stopped";
  return el("span", `status status-${text.toLowerCase().replaceAll(" ", "-")}`, text);
}

function telemetryLabel(key) {
  return state.failures.has(key) ? "Unavailable" : "Loading";
}

function gpuUnavailableText() {
  return state.failures.has("gpu") ? "nvidia-smi is unavailable" : "Waiting for nvidia-smi";
}

function emptyState(title, detail, actionLabel = "", href = "") {
  const node = el("div", "empty-state");
  node.append(el("strong", "", title), el("p", "muted", detail));
  if (actionLabel && href) {
    const action = el("a", "secondary-link", actionLabel);
    action.href = href;
    node.append(action);
  }
  return node;
}

function meta(label, value) {
  const p = el("p", "recipe-meta");
  p.append(el("strong", "", `${label}: `), textNode(String(value)));
  return p;
}

function option(value, label) {
  const node = document.createElement("option");
  node.value = value;
  node.textContent = label;
  return node;
}

function labelize(key) {
  return key.replace(/([A-Z])/g, " $1").replace(/^./, (letter) => letter.toUpperCase());
}

function registerServiceWorker() {
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js");
}

function byId(id) {
  return document.getElementById(id);
}

function setText(id, text) {
  byId(id).textContent = text;
}

function el(tag, className = "", text = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}

function textNode(text) {
  return document.createTextNode(text);
}

function replaceChildren(parent, children) {
  parent.replaceChildren(...children);
}