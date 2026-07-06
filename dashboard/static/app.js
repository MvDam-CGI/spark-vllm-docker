const state = {
  recipes: [],
  runtimes: [],
  gpu: null,
  system: null,
  settings: null,
  failures: new Map(),
  openDetails: new Set(),
  launchLogTimer: null,
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

function showLaunchTab(tab) {
  document.querySelectorAll("[data-launch-tab]").forEach((button) => {
    button.setAttribute("aria-selected", String(button.dataset.launchTab === tab));
  });
  document.querySelectorAll("[data-launch-tab-panel]").forEach((panel) => {
    panel.hidden = panel.dataset.launchTabPanel !== tab;
  });
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

function renderOverview() {
  const active = activeRuntimes();
  setText("running-title", state.system?.host ? `Models on ${state.system.host}` : "Models on this Spark");
  setText("running-count-badge", active.length ? `${active.length} active` : "Nothing running");
  renderOverviewRuntimes();
  renderCapacityPanel();
  replaceChildren(byId("capabilities"), capabilityCards());
  replaceChildren(byId("recent-events"), recentEvents());
}

function renderOverviewRuntimes() {
  const active = activeRuntimes();
  const nodes = active.length
    ? active.map((runtime) => runtimeCard(runtime, { compact: true }))
    : [emptyState("No models are running", "The Spark is idle. Use Launch to dry run a recipe and then start a model when capacity is available.", "Start a model", "#launch")];
  replaceChildren(byId("overview-runtimes"), nodes);
}

function activeRuntimes() {
  return state.runtimes.filter((runtime) => ["Starting", "Running", "Ready"].includes(runtime.status));
}

function renderCapacityPanel() {
  const gpu = state.gpu?.gpus?.[0];
  const memory = state.system?.memory;
  const disk = state.system?.disk;
  const activePorts = activeRuntimes().map((runtime) => runtime.port).filter(Boolean).join(", ") || "None";
  const ready = state.runtimes.filter((runtime) => runtime.status === "Ready").length;
  const gpuPercent = typeof gpu?.memoryPercent === "number" ? gpu.memoryPercent : null;
  const rows = [
    meterRow("GPU memory", gpuPercent, gpuMemoryValue(gpu), gpuMemoryDetail(gpu)),
    meterRow("System memory", memory ? memory.usedPercent : null, memory ? `${memory.usedPercent}%` : "Unavailable", memory ? `${memory.usedMiB} MiB used` : telemetryLabel("system")),
    meterRow("Disk", disk ? disk.usedPercent : null, disk ? `${disk.usedPercent}%` : "Unavailable", disk ? `${disk.freeGiB} GiB free` : telemetryLabel("system")),
    summaryRow("Recipes", state.recipes.length || "Loading"),
    summaryRow("Active ports", activePorts),
    summaryRow("Ready endpoints", ready),
  ];
  replaceChildren(byId("capacity-panel"), rows);
}

function meterRow(label, percent, value, detail) {
  const row = el("div", "capacity-row");
  const top = el("div", "capacity-row-top");
  top.append(el("span", "", label), el("strong", "", value));
  const meter = document.createElement("meter");
  meter.min = 0;
  meter.max = 100;
  meter.value = percent === null ? 0 : percent;
  if (percent === null) meter.classList.add("is-unknown");
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
    item.append(statusPill(runtime.status), textNode(` ${runtimeDisplayName(runtime)} on port ${runtime.port}`));
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
  const runningSlugs = new Set(state.runtimes.filter((runtime) => ["Starting", "Running", "Ready"].includes(runtime.status)).map((runtime) => runtime.recipeSlug));
  const recipes = state.recipes.filter((recipe) => {
    if (filter === "solo") return !recipe.clusterOnly;
    if (filter === "cluster") return !recipe.soloOnly;
    if (filter === "running") return runningSlugs.has(recipe.slug);
    if (filter === "cached") return recipe.modelAvailability?.downloaded === true;
    if (filter === "needs-download") return recipe.modelAvailability?.downloaded === false;
    if (filter === "ready") return !runningSlugs.has(recipe.slug);
    return true;
  });
  const nodes = recipes.length ? recipes.map(recipeCard) : [emptyState("No recipes match this view", "Try All, Model downloaded, or Not running.")];
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
  const details = detailsElement(`recipe:${recipe.slug}`, "Recipe details");
  details.append(
    meta("Model ID", recipe.model || "Not specified"),
    meta("Model cache", recipe.modelAvailability?.detail || "Availability check is unavailable."),
    meta("Container", recipe.container),
    meta("Default port", recipe.defaultPort),
    meta("GPU target", recipe.defaultGpuMemoryUtilization),
    meta("Max model length", recipe.defaultMaxModelLen),
    meta("Mods", recipe.mods.length ? recipe.mods.join(", ") : "None"),
  );
  card.append(
    el("h2", "", recipe.name),
    el("div", "recipe-badges", availabilityBadge(recipe.modelAvailability), availabilityBadge(runningRecipeLabel(recipe.slug))),
    el("p", "muted", recipe.description || "No description provided."),
    meta("Support", recipe.support),
    details,
    launch,
  );
  return card;
}

function runningRecipeLabel(slug) {
  const isRunning = state.runtimes.some((runtime) => ["Starting", "Running", "Ready"].includes(runtime.status) && runtime.recipeSlug === slug);
  return isRunning
    ? { status: "running", label: "Already running" }
    : { status: "not-running", label: "Not running" };
}

function availabilityBadge(availability) {
  const status = availability?.status || "unknown";
  const label = availability?.label || "Availability unknown";
  return el("span", `availability-badge availability-${status}`, label);
}

function renderRuntime() {
  renderMonitoringSummary();
  const nodes = state.runtimes.length ? state.runtimes.map((runtime) => runtimeCard(runtime)) : [emptyState("No runtime selected", "Dashboard-launched runtimes will appear here with health, port, and log actions.")];
  replaceChildren(byId("runtime-list"), nodes);
}

function renderMonitoringSummary() {
  const withMetrics = state.runtimes.filter((runtime) => runtime.tokenMetrics);
  const generatedToday = sumGeneratedTokens(withMetrics.filter((runtime) => isToday(runtime.startedAt)));
  const generatedTotal = sumGeneratedTokens(withMetrics);
  const peakOutput = Math.max(0, ...withMetrics.map((runtime) => runtime.tokenMetrics?.peakGeneratedTokensPerSecond).filter((value) => typeof value === "number"));
  replaceChildren(byId("monitoring-summary"), [
    metricTile("Generated today", tokenMetricValue(generatedToday), "dashboard runtime history"),
    metricTile("Generated total", tokenMetricValue(generatedTotal), "stored runtime totals"),
    metricTile("Peak output", peakOutput ? `${peakOutput.toFixed(1)} tok/s` : "Not available", "observed aggregate rate"),
  ]);
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
  if (options.compact) {
    const monitor = el("button", "secondary-button", "Monitor");
    monitor.type = "button";
    monitor.addEventListener("click", () => {
      location.hash = "runtime";
    });
    actions.append(monitor);
  }
  actions.append(logs, stop);
  const details = detailsElement(`runtime:${runtime.id}`, "More runtime details");
  details.append(
    meta("Runtime name", runtime.id),
    meta("Project", runtime.projectName || (runtime.mode === "Manual" ? "Manual" : "None")),
    meta("API base URL", `http://127.0.0.1:${runtime.port}/v1`),
    meta("Container name", runtime.containerName || "Unknown"),
    meta("Last health check", runtime.health?.healthy ? "Ready" : "Not ready yet"),
    runtimeMemoryPanel(runtime),
  );
  card.append(
    el("h2", "", runtimeDisplayName(runtime)),
    statusPill(runtime.status),
    meta("Port", runtime.port),
    meta("Mode", runtime.mode || "Unknown"),
    runtimeGpuSummary(runtime),
    options.compact ? runtimeTokenSummary(runtime) : runtimeTokenPanel(runtime),
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
  byId("launch-max-batched-tokens").value = recipe.defaults?.max_num_batched_tokens || "";
  byId("launch-max-seqs").value = recipe.defaults?.max_num_seqs || "";
  setText("selected-recipe-summary", `${recipe.name}. ${recipe.description || "No description provided."}`);
  updateCommandPreview();
}

function updateCommandPreview() {
  const payload = launchPayload();
  if (!payload.recipeSlug) {
    setText("command-preview", "Waiting for recipes...");
    return;
  }
  const args = ["./run-recipe.sh", payload.recipeSlug, "--port", payload.port || "", "--host", payload.host || ""];
  args.push("--gpu-mem", payload.gpuMemoryUtilization || "", "--max-model-len", payload.maxModelLen || "");
  if (payload.maxNumBatchedTokens) args.push("--max-num-batched-tokens", payload.maxNumBatchedTokens);
  if (payload.maxNumSeqs) args.push("--max-num-seqs", payload.maxNumSeqs);
  args.push("--tp", payload.tensorParallel || "1");
  args.push("--name", `vllm-${payload.recipeSlug}-${payload.port || "port"}-<run-id>`);
  if (payload.containerOverride) args.push("--container", payload.containerOverride);
  args.push(payload.mode === "solo" ? "--solo" : "--no-ray");
  if (payload.nodes) args.push("--nodes", payload.nodes);
  if (payload.setup) args.push("--setup");
  if (payload.buildOnly) args.push("--build-only");
  if (payload.downloadOnly) args.push("--download-only");
  if (payload.forceBuild) args.push("--force-build");
  if (payload.forceDownload) args.push("--force-download");
  if (payload.daemon) args.push("--daemon");
  if (payload.ncclDebug) args.push("--nccl-debug", payload.ncclDebug);
  payload.envVars.forEach((value) => args.push("--env", value));
  payload.applyMods.forEach((value) => args.push("--apply-mod", value));
  payload.publishPorts.forEach((value) => args.push("--publish", value));
  if (payload.masterPort) args.push("--master-port", payload.masterPort);
  if (payload.ethIf) args.push("--eth-if", payload.ethIf);
  if (payload.ibIf) args.push("--ib-if", payload.ibIf);
  if (payload.buildJobs) args.push("-j", payload.buildJobs);
  if (payload.noCacheDirs) args.push("--no-cache-dirs");
  if (payload.keepEntrypoint) args.push("--keep-entrypoint");
  if (payload.nonPrivileged) args.push("--non-privileged");
  if (payload.memLimitGb) args.push("--mem-limit-gb", payload.memLimitGb);
  if (payload.memSwapLimitGb) args.push("--mem-swap-limit-gb", payload.memSwapLimitGb);
  if (payload.pidsLimit) args.push("--pids-limit", payload.pidsLimit);
  if (payload.shmSizeGb) args.push("--shm-size-gb", payload.shmSizeGb);
  if (payload.dryRun) args.push("--dry-run");
  if (payload.extraVllmArgs) args.push("--", payload.extraVllmArgs);
  setText("gpu-memory-output", payload.gpuMemoryUtilization || "");
  setText("command-preview", args.join(" "));
}

async function launchRuntime(event) {
  event.preventDefault();
  setText("launch-status", "Submitting launch request...");
  setText("launch-output", "");
  setText("launch-live-logs", "Waiting for startup logs...");
  try {
    const result = await apiPost("/api/runtimes", launchPayload());
    if (launchPayload().dryRun) {
      setText("launch-status", result.status === "Ready" ? "Dry run completed." : "Dry run needs attention.");
      setText("launch-live-logs", result.output || "No dry-run output returned.");
    } else {
      setText("launch-status", `Starting ${result.launchId}. Watching startup logs...`);
      watchLaunchLogs(result.launchId);
    }
    await refreshAll();
  } catch (error) {
    setText("launch-status", "Launch request failed.");
    setText("launch-output", error.message);
  }
}

function watchLaunchLogs(runtimeId) {
  if (state.launchLogTimer) clearInterval(state.launchLogTimer);
  refreshLaunchLogs(runtimeId);
  state.launchLogTimer = setInterval(() => refreshLaunchLogs(runtimeId), 2000);
}

async function refreshLaunchLogs(runtimeId) {
  try {
    const [logsResult, runtimesResult] = await Promise.all([apiGet(`/api/logs/${runtimeId}?lines=180`), apiGet("/api/runtimes")]);
    setText("launch-live-logs", logsResult.logs || "Startup logs are not available yet.");
    const runtime = (runtimesResult.runtimes || []).find((item) => item.id === runtimeId);
    if (runtime) {
      setText("launch-status", `${runtime.recipeName}: ${runtime.status}`);
      if (["Ready", "Needs Attention", "Manually Stopped", "Exited", "Stopped"].includes(runtime.status) && state.launchLogTimer) {
        clearInterval(state.launchLogTimer);
        state.launchLogTimer = null;
      }
    }
  } catch (error) {
    setText("launch-status", "Startup log polling is unavailable.");
  }
}

async function stopRuntime(runtimeId) {
  const dialog = byId("confirm-dialog");
  dialog.showModal();
  const confirmed = await new Promise((resolve) => {
    dialog.addEventListener("close", () => resolve(dialog.returnValue === "confirm"), { once: true });
  });
  if (!confirmed) return;
  try {
    const result = await apiPost(`/api/runtimes/${runtimeId}/stop`, {});
    if (!result.stopped) throw new Error("Stop could not terminate this runtime. Check that it is still a vLLM process and that the dashboard has permission to stop it.");
    await refreshAll();
  } catch (error) {
    setText("connection-state", error.message);
    if (error.message.includes("control token")) location.hash = "settings";
  }
}

function renderLogsOptions() {
  const select = byId("logs-runtime");
  const selected = select.value;
  replaceChildren(select, state.runtimes.map((runtime) => option(runtime.id, runtimeDisplayName(runtime))));
  select.value = state.runtimes.some((runtime) => runtime.id === selected) ? selected : state.runtimes[0]?.id || "";
  renderLogRuntimeGroups();
  if (!state.runtimes.length) {
    setText("logs-current-runtime", "No runtime selected.");
    setText("raw-logs", "No runtime logs yet. Launch a runtime or dry run first.");
  }
}

function renderLogRuntimeGroups() {
  const selected = byId("logs-runtime").value;
  const active = activeRuntimes();
  const history = state.runtimes.filter((runtime) => !["Starting", "Running", "Ready"].includes(runtime.status));
  const groups = [
    logRuntimeSection("Running now", active, selected),
    logRuntimeSection("History", history, selected),
  ];
  replaceChildren(byId("logs-runtime-groups"), groups);
}

function logRuntimeSection(title, runtimes, selected) {
  const section = el("section", "log-runtime-section");
  section.append(el("h2", "", title));
  if (!runtimes.length) {
    section.append(emptyState(title === "Running now" ? "No active runtime logs" : "No historical runtime logs", "Runs will appear here as soon as the dashboard has metadata for them."));
    return section;
  }
  const grid = el("div", "log-runtime-grid");
  runtimes.forEach((runtime) => grid.append(logRuntimeButton(runtime, selected)));
  section.append(grid);
  return section;
}

function logRuntimeButton(runtime, selected) {
  const button = el("button", "log-runtime-button");
  button.type = "button";
  button.classList.toggle("is-selected", runtime.id === selected);
  button.addEventListener("click", () => {
    byId("logs-runtime").value = runtime.id;
    refreshLogs();
    renderLogRuntimeGroups();
  });
  button.append(
    statusPill(runtime.status),
    el("strong", "", runtimeDisplayName(runtime)),
    el("span", "muted", `Port ${runtime.port} · ${formatStartedAt(runtime.startedAt)}`),
    el("code", "", shortRuntimeId(runtime.id)),
  );
  return button;
}

async function refreshLogs() {
  const runtimeId = byId("logs-runtime").value;
  if (!runtimeId) return;
  const runtime = state.runtimes.find((item) => item.id === runtimeId);
  if (runtime) {
    setText("logs-current-runtime", `${runtimeDisplayName(runtime)} is ${runtime.status} on port ${runtime.port}. Run ${shortRuntimeId(runtime.id)}.`);
  }
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
    projectName: data.get("projectName"),
    mode: data.get("mode"),
    port: Number(data.get("port")),
    host: data.get("host"),
    gpuMemoryUtilization: Number(data.get("gpuMemoryUtilization")),
    maxModelLen: Number(data.get("maxModelLen")),
    maxNumBatchedTokens: optionalNumber(data.get("maxNumBatchedTokens")),
    maxNumSeqs: optionalNumber(data.get("maxNumSeqs")),
    tensorParallel: Number(data.get("tensorParallel") || 1),
    nodes: data.get("nodes"),
    containerOverride: data.get("containerOverride"),
    ncclDebug: data.get("ncclDebug"),
    envVars: listField("launch-env-vars"),
    applyMods: listField("launch-apply-mods"),
    publishPorts: listField("launch-publish-ports"),
    masterPort: optionalNumber(data.get("masterPort")),
    ethIf: data.get("ethIf"),
    ibIf: data.get("ibIf"),
    buildJobs: optionalNumber(data.get("buildJobs")),
    memLimitGb: optionalNumber(data.get("memLimitGb")),
    memSwapLimitGb: optionalNumber(data.get("memSwapLimitGb")),
    pidsLimit: optionalNumber(data.get("pidsLimit")),
    shmSizeGb: optionalNumber(data.get("shmSizeGb")),
    extraVllmArgs: data.get("extraVllmArgs"),
    setup: byId("launch-setup").checked,
    buildOnly: byId("launch-build-only").checked,
    downloadOnly: byId("launch-download-only").checked,
    forceBuild: byId("launch-force-build").checked,
    forceDownload: byId("launch-force-download").checked,
    daemon: byId("launch-daemon").checked,
    noCacheDirs: byId("launch-no-cache-dirs").checked,
    keepEntrypoint: byId("launch-keep-entrypoint").checked,
    nonPrivileged: byId("launch-non-privileged").checked,
    dryRun: byId("launch-dry-run").checked,
  };
}

function listField(id) {
  return byId(id).value.split(/[\n,]+/).map((item) => item.trim()).filter(Boolean);
}

function optionalNumber(value) {
  return value === null || value === "" ? null : Number(value);
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
      "X-Dashboard-Token": currentControlToken(),
    },
    body: JSON.stringify(payload),
  });
  return readJson(response);
}

function currentControlToken() {
  return byId("control-token").value || sessionStorage.getItem(tokenKey) || "";
}

async function readJson(response) {
  const data = await response.json();
  if (!response.ok) {
    if (response.status === 401) throw new Error("Set the dashboard control token in Settings, then try again.");
    throw new Error(data.error || "Request failed.");
  }
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

function runtimeDisplayName(runtime) {
  const prefix = runtime.projectName || (runtime.mode === "Manual" ? "Manual" : "");
  return prefix ? `${prefix} - ${runtime.recipeName}` : runtime.recipeName;
}

function shortRuntimeId(runtimeId) {
  const text = String(runtimeId || "");
  return text.length > 20 ? text.slice(-20) : text;
}

function formatStartedAt(startedAt) {
  if (!startedAt) return "manual process";
  const date = new Date(startedAt);
  if (Number.isNaN(date.getTime())) return "time unknown";
  return date.toLocaleString([], { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function runtimeGpuSummary(runtime) {
  const panel = el("div", "runtime-gpu-summary");
  const percent = runtimeGpuPercent(runtime);
  panel.append(
    el("strong", "", percent === null ? "GPU target unknown" : `${percent}% GPU memory`),
    el("p", "muted", runtimeGpuSource(runtime)),
  );
  return panel;
}

function runtimeGpuPercent(runtime) {
  if (typeof runtime.gpuMemoryPercent === "number") return runtime.gpuMemoryPercent;
  if (typeof runtime.gpuMemoryTargetPercent === "number") return runtime.gpuMemoryTargetPercent;
  return null;
}

function runtimeGpuSource(runtime) {
  if (runtime.gpuMemorySource === "observed process memory") {
    return `${formatMiB(runtime.gpuMemoryObservedMiB)} observed by nvidia-smi`;
  }
  if (typeof runtime.gpuMemoryTargetPercent === "number") return "Configured launch target";
  return "No GPU target was recorded for this runtime";
}

function runtimeMemoryPanel(runtime) {
  const panel = el("div", "runtime-memory");
  panel.append(
    memoryLine("GPU target", typeof runtime.gpuMemoryTargetPercent === "number" ? `${runtime.gpuMemoryTargetPercent}%` : "Not recorded"),
    memoryLine("Observed GPU memory", observedGpuValue(runtime), runtime.gpuMemoryObservedMiB),
    memoryLine("Model weights", memoryValue(runtime.memoryBreakdown?.modelMiB), runtime.memoryBreakdown?.modelMiB),
    memoryLine("Context / KV cache", memoryValue(runtime.memoryBreakdown?.contextMiB), runtime.memoryBreakdown?.contextMiB),
  );
  return panel;
}

function runtimeTokenSummary(runtime) {
  const metrics = runtime.tokenMetrics || {};
  const summary = el("p", "runtime-token-summary muted");
  const generated = metrics.generationTokensTotal;
  const lastActiveRate = metrics.lastActiveGeneratedTokensPerSecond;
  if (typeof generated !== "number" && typeof lastActiveRate !== "number") {
    summary.textContent = "Token metrics waiting for vLLM telemetry";
    return summary;
  }
  const parts = [];
  if (typeof generated === "number") parts.push(`${formatCount(generated)} generated tokens`);
  if (typeof lastActiveRate === "number") parts.push(`${lastActiveRate} agg tok/s`);
  summary.textContent = parts.join(" · ");
  return summary;
}

function runtimeTokenPanel(runtime) {
  const metrics = runtime.tokenMetrics || {};
  const panel = el("div", "runtime-token-panel");
  panel.append(
    metricTile("Generated", tokenMetricValue(metrics.generationTokensTotal), tokenSourceLabel(metrics.source)),
    metricTile("Prompt", tokenMetricValue(metrics.promptTokensTotal), "input tokens"),
    metricTile("Total", tokenMetricValue(metrics.tokensTotal), "prompt plus generated"),
    metricTile("Requests", tokenMetricValue(metrics.requestCount), "completed by vLLM"),
    metricTile("Current output", tokensPerSecondValue(metrics.currentGeneratedTokensPerSecond), "latest dashboard sample"),
    metricTile("Last active output", tokensPerSecondValue(metrics.lastActiveGeneratedTokensPerSecond), "latest positive sample"),
    metricTile("Peak output", tokensPerSecondValue(metrics.peakGeneratedTokensPerSecond), "highest observed sample"),
    metricTile("TPOT", millisecondsValue(metrics.timePerOutputTokenMs), "avg time per output token"),
    metricTile("E2E latency", secondsValue(metrics.endToEndLatencySeconds), "avg per request"),
    metricTile("KV cache", percentValue(metrics.kvCacheUsagePercent), "current usage"),
    metricTile("Prefix hits", percentValue(metrics.prefixCacheHitPercent), "cached prompt tokens"),
  );
  return panel;
}

function metricTile(label, value, detail) {
  const tile = el("div", "metric-tile");
  tile.append(el("span", "metric-label", label), el("strong", "", value), el("p", "muted", detail));
  return tile;
}

function tokenMetricValue(value) {
  return typeof value === "number" ? formatCount(value) : "Not available";
}

function tokensPerSecondValue(value) {
  return typeof value === "number" ? `${value} tok/s` : "Not available";
}

function millisecondsValue(value) {
  return typeof value === "number" ? `${value} ms` : "Not available";
}

function secondsValue(value) {
  return typeof value === "number" ? `${value} s` : "Not available";
}

function percentValue(value) {
  return typeof value === "number" ? `${value}%` : "Not available";
}

function sumGeneratedTokens(runtimes) {
  return runtimes.reduce((total, runtime) => {
    const value = runtime.tokenMetrics?.generationTokensTotal;
    return total + (typeof value === "number" ? value : 0);
  }, 0);
}

function isToday(value) {
  if (!value) return false;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return false;
  const now = new Date();
  return date.getFullYear() === now.getFullYear() && date.getMonth() === now.getMonth() && date.getDate() === now.getDate();
}

function tokenSourceLabel(source) {
  if (source === "prometheus") return "exact vLLM counter";
  return "waiting for metrics";
}

function formatCount(value) {
  if (typeof value !== "number") return "Not available";
  return Math.round(value).toLocaleString();
}

function observedGpuValue(runtime) {
  if (typeof runtime.gpuMemoryObservedMiB === "number") return formatMiB(runtime.gpuMemoryObservedMiB);
  return "Only attributable when a single active vLLM process is visible";
}

function memoryLine(label, value, mib) {
  const row = el("div", "memory-line");
  row.append(el("span", "", label), el("strong", "", value));
  if (typeof mib === "number") row.title = formatMiB(mib);
  return row;
}

function memoryValue(mib) {
  return typeof mib === "number" ? formatMiB(mib) : "Not reported";
}

function formatMiB(mib) {
  if (typeof mib !== "number") return "Unknown";
  if (mib >= 1024) return `${(mib / 1024).toFixed(1)} GiB`;
  return `${Math.round(mib).toLocaleString()} MiB`;
}

function telemetryLabel(key) {
  return state.failures.has(key) ? "Unavailable" : "Loading";
}

function gpuMemoryValue(gpu) {
  if (!gpu) return "Unavailable";
  if (typeof gpu.memoryPercent === "number") return `${gpu.memoryPercent}%`;
  if (gpu.memoryUsedMiB) return `${Math.round(gpu.memoryUsedMiB).toLocaleString()} MiB`;
  return "Unavailable";
}

function gpuMemoryDetail(gpu) {
  if (!gpu) return gpuUnavailableText();
  if (typeof gpu.memoryPercent === "number") return `${formatMiB(gpu.memoryUsedMiB)} of ${formatMiB(gpu.memoryTotalMiB)} estimated total.`;
  if (gpu.memoryUsedMiB) return `${formatMiB(gpu.memoryUsedMiB)} of ${formatMiB(gpu.memoryTotalMiB)} estimated total.`;
  return "GPU memory telemetry is unavailable.";
}

function gpuUnavailableText() {
  return state.failures.has("gpu") ? "nvidia-smi is unavailable" : "Waiting for nvidia-smi";
}

function detailsElement(key, summaryText) {
  const details = document.createElement("details");
  details.dataset.detailKey = key;
  details.open = state.openDetails.has(key);
  details.append(el("summary", "", summaryText));
  return details;
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

