const API_BASE_URL = "http://localhost:8000";

async function fetchDegrees() {
  const response = await fetch(`${API_BASE_URL}/advisor/degrees`);

  if (!response.ok) {
    throw new Error(`Could not load degrees (${response.status})`);
  }

  return response.json();
}

async function fetchRecommendations(payload) {
  const response = await fetch(`${API_BASE_URL}/advisor/recommend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    let details = "";
    try {
      const body = await response.json();
      details = body?.detail ? `: ${body.detail}` : "";
    } catch {
      details = "";
    }
    throw new Error(`Request failed (${response.status})${details}`);
  }

  return response.json();
}
