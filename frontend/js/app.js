const form = document.getElementById("advisor-form");
const output = document.getElementById("output");

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  const major = document.getElementById("major").value.trim();
  const completedRaw = document.getElementById("completed").value.trim();

  const payload = {
    major,
    completed_courses: completedRaw
      ? completedRaw.split(",").map((c) => c.trim()).filter(Boolean)
      : [],
    interests: [],
    career_goals: [],
    prefer_light_workload: false,
    prefer_high_rated_professors: false,
  };

  output.textContent = "Loading...";

  try {
    const data = await fetchRecommendations(payload);
    output.textContent = JSON.stringify(data, null, 2);
  } catch (error) {
    output.textContent = `Error: ${error.message}`;
  }
});
