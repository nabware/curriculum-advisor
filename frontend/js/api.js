const ADVISOR_API_BASE_URL = "http://localhost:8000";

async function fetchDegrees() {
  const response = await fetch(`${ADVISOR_API_BASE_URL}advisor/degrees`);

  if (!response.ok) {
    throw new Error(`Could not load degrees (${response.status})`);
  }

  return response.json();
}

async function fetchRecommendations(payload) {
  const response = await fetch(`${ADVISOR_API_BASE_URL}/advisor/recommend`, {
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

async function fetchProfessorRating(name) {
  const response = await fetch(`${ADVISOR_API_BASE_URL}/advisor/professor-rating?name=${encodeURIComponent(name)}`);

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

async function sendChatMessage(payload) {
  const response = await fetch(`${ADVISOR_API_BASE_URL}/advisor/chat`, {
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
    throw new Error(`Chat request failed (${response.status})${details}`);
  }

  return response.json();
}
window.sendChatMessage = sendChatMessage;
window.fetchProfessorRating = fetchProfessorRating;
window.fetchRecommendations = fetchRecommendations;
window.fetchDegrees = fetchDegrees;