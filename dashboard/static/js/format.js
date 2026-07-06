export function formatStartedAt(startedAt) {
  if (!startedAt) return "manual process";
  const date = new Date(startedAt);
  if (Number.isNaN(date.getTime())) return "time unknown";
  return date.toLocaleString([], { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export function tokenMetricValue(value) {
  return typeof value === "number" ? formatCount(value) : "Not available";
}

export function tokensPerSecondValue(value) {
  return typeof value === "number" ? `${value} tok/s` : "Not available";
}

export function millisecondsValue(value) {
  return typeof value === "number" ? `${value} ms` : "Not available";
}

export function secondsValue(value) {
  return typeof value === "number" ? `${value} s` : "Not available";
}

export function percentValue(value) {
  return typeof value === "number" ? `${value}%` : "Not available";
}

export function formatCount(value) {
  if (typeof value !== "number") return "Not available";
  return Math.round(value).toLocaleString();
}

export function memoryValue(mib) {
  return typeof mib === "number" ? formatMiB(mib) : "Not reported";
}

export function formatMiB(mib) {
  if (typeof mib !== "number") return "Unknown";
  if (mib >= 1024) return `${(mib / 1024).toFixed(1)} GiB`;
  return `${Math.round(mib).toLocaleString()} MiB`;
}
