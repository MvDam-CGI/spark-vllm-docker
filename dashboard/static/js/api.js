import { currentControlToken } from "./core.js";

export async function apiGet(path) {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  return readJson(response);
}

export async function apiPost(path, payload) {
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

async function readJson(response) {
  const data = await response.json();
  if (!response.ok) {
    if (response.status === 401) throw new Error("Set the dashboard control token in Settings, then try again.");
    throw new Error(data.error || "Request failed.");
  }
  return data;
}
