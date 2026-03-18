const API_BASE_URL = "http://localhost:8000";

async function fetchRecommendations(payload) {
  const response = await fetch(`${API_BASE_URL}/advisor/recommend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    throw new Error(`Request failed with status ${response.status}`);
  }

  return response.json();
}
