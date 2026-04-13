const DEFAULT_HEADERS = {
  "Content-Type": "application/json",
};

async function request(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `${response.status} ${response.statusText}`);
  }
  return response.json();
}

export function fetchMetrics() {
  return request("/api/metrics");
}

export function fetchSkills() {
  return request("/api/skills");
}

export function fetchPatches() {
  return request("/api/patches");
}

export function fetchSystemStatus() {
  return request("/api/system_status");
}

export function fetchLoopState() {
  return request("/api/loop_state");
}

export function fetchDebugStream() {
  return request("/api/debug_stream");
}

export function fetchPolicy() {
  return request("/api/policy");
}

export function updatePolicy(policy, adminToken) {
  return request("/api/policy", {
    method: "PUT",
    headers: {
      ...DEFAULT_HEADERS,
      "X-AIWorker-Admin": adminToken || "",
    },
    body: JSON.stringify(policy),
  });
}

export function approvePatch(patchId, adminToken) {
  return request(`/api/patches/${patchId}/approve`, {
    method: "POST",
    headers: {
      ...DEFAULT_HEADERS,
      "X-AIWorker-Admin": adminToken || "",
    },
  });
}

export function rollbackPatch(patchId, adminToken) {
  return request(`/api/patches/${patchId}/rollback`, {
    method: "POST",
    headers: {
      ...DEFAULT_HEADERS,
      "X-AIWorker-Admin": adminToken || "",
    },
  });
}
