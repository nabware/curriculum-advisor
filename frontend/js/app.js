const form = document.getElementById("advisor-form");
const degreeSelect = document.getElementById("degree-select");
const statusEl = document.getElementById("status");
const explanationEl = document.getElementById("explanation");
const recommendationsEl = document.getElementById("recommendations");
const submitBtn = document.getElementById("submit-btn");

// ── Blocked time windows state ───────────────────────────────────────────────
const blockedWindows = []; // { day, start, end } objects

function formatTime24To12(hhmm) {
  const [hStr, mStr] = hhmm.split(":");
  let h = parseInt(hStr, 10);
  const m = mStr || "00";
  const period = h >= 12 ? "PM" : "AM";
  if (h === 0) h = 12;
  else if (h > 12) h -= 12;
  return `${h}:${m}${period}`;
}

function renderBlockedWindows() {
  const list = document.getElementById("blocked-windows-list");
  list.innerHTML = "";
  blockedWindows.forEach((w, idx) => {
    const chip = document.createElement("span");
    chip.className = "blocked-chip";
    chip.textContent = `${w.day} ${formatTime24To12(w.start)} – ${formatTime24To12(w.end)}`;
    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "blocked-chip-remove";
    removeBtn.setAttribute("aria-label", `Remove ${chip.textContent}`);
    removeBtn.textContent = "×";
    removeBtn.addEventListener("click", () => {
      blockedWindows.splice(idx, 1);
      renderBlockedWindows();
    });
    chip.appendChild(removeBtn);
    list.appendChild(chip);
  });
}

document.getElementById("add-blocked-btn").addEventListener("click", () => {
  const day = document.getElementById("blocked-day").value;
  const start = document.getElementById("blocked-start").value;
  const end = document.getElementById("blocked-end").value;
  if (!start || !end || start >= end) {
    setStatus("Blocked window: end time must be after start time.", true);
    return;
  }
  blockedWindows.push({ day, start, end });
  renderBlockedWindows();
});

// ── Transcript drag-and-drop ─────────────────────────────────────────────────
const dropzone = document.getElementById("transcript-dropzone");
const transcriptTextarea = document.getElementById("transcript-text");

dropzone.addEventListener("dragover", (e) => {
  e.preventDefault();
  dropzone.classList.add("drag-over");
});
dropzone.addEventListener("dragleave", () => dropzone.classList.remove("drag-over"));
dropzone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropzone.classList.remove("drag-over");
  const file = e.dataTransfer?.files?.[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = (ev) => {
    transcriptTextarea.value = ev.target.result || "";
  };
  reader.readAsText(file);
});

function setStatus(message, isError = false) {
  statusEl.textContent = message;
  statusEl.classList.toggle("error", isError);
}

function hashString(value) {
  let hash = 0;
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 31 + value.charCodeAt(index)) >>> 0;
  }
  return hash;
}

function buildAvatarDataUrl(name) {
  const safeName = (name || "Professor").trim() || "Professor";
  const initials = safeName
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part.charAt(0).toUpperCase())
    .join("") || "P";
  const palette = ["#1c6b57", "#165241", "#8d5b2d", "#7a4d6e", "#4c6a8a"];
  const color = palette[hashString(safeName) % palette.length];
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" width="120" height="120" viewBox="0 0 120 120">
      <rect width="120" height="120" rx="60" fill="${color}" />
      <text x="60" y="69" text-anchor="middle" font-family="Manrope, Arial, sans-serif" font-size="40" font-weight="700" fill="#fff">${initials}</text>
    </svg>
  `;
  return `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg.trim())}`;
}

function getRenderableProfessorImageUrl(imageUrl) {
  const value = (imageUrl || "").trim();
  if (!value) {
    return null;
  }

  // Only allow image sources that the browser can reliably resolve from the app.
  if (/^https?:\/\//i.test(value) || value.startsWith("data:image/")) {
    return value;
  }

  // Backend returns root-relative asset paths; make them absolute to backend origin.
  if (value.startsWith("/") && typeof API_BASE_URL === "string" && API_BASE_URL) {
    return `${API_BASE_URL}${value}`;
  }

  return null;
}

function renderRecommendations(groups, fallbackCourses = []) {
  recommendationsEl.innerHTML = "";

  // Flatten all courses from groups
  let allCourses = [];
  if (groups.length) {
    groups.forEach((group) => {
      group.courses.forEach((course) => {
        allCourses.push({
          ...course,
          group_name: group.group_name
        });
      });
    });
  }

  // Add fallback courses if no groups
  if (!allCourses.length && fallbackCourses.length) {
    allCourses = fallbackCourses;
  }

  if (!allCourses.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "No courses matched yet for the selected degree.";
    recommendationsEl.appendChild(empty);
    return;
  }

  allCourses.forEach((course) => {
    const article = document.createElement("article");
    article.className = "recommendation-card";

    const code = document.createElement("p");
    code.className = "course-code";
    code.textContent = course.course_code;

    const courseTitle = document.createElement("h4");
    courseTitle.textContent = course.title;

    const meta = document.createElement("p");
    meta.className = "course-meta";
    const groupName = course.group_name || "Requirement group not specified";
    const units = Number.isInteger(course.units) ? `${course.units} units` : "Units TBD";
    meta.textContent = `${units} | ${groupName}`;

    const schedule = document.createElement("p");
    schedule.className = "course-schedule";
    const daysTimes = course.days_times || "Time not available";
    schedule.textContent = daysTimes;

    const description = document.createElement("p");
    description.className = "course-description";
    description.textContent = course.description || "Course description not available.";

    const professor = document.createElement("div");
    professor.className = "professor-card";

    const professorImage = document.createElement("img");
    professorImage.className = "professor-image";
    professorImage.alt = course.professor_name || course.instructor || "Professor";
    const fallbackAvatar = buildAvatarDataUrl(course.professor_name || course.instructor || "Professor");
    professorImage.src = getRenderableProfessorImageUrl(course.professor_image_url) || fallbackAvatar;
    professorImage.addEventListener("error", () => {
      professorImage.src = fallbackAvatar;
    }, { once: true });

    const professorMeta = document.createElement("div");
    professorMeta.className = "professor-meta";

    const professorName = document.createElement("p");
    professorName.className = "professor-name";
    professorName.textContent = course.professor_name || course.instructor || "Professor not available";

    professorMeta.appendChild(professorName);

    // RMP ratings
    if (course.rmp_rating !== null && course.rmp_rating !== undefined) {
      const rmpBadge = document.createElement("div");
      rmpBadge.className = "rmp-badge";

      const ratingEl = document.createElement("span");
      ratingEl.className = "rmp-rating";
      ratingEl.title = `Based on ${course.rmp_num_ratings ?? "?"} ratings`;
      ratingEl.textContent = `${course.rmp_rating.toFixed(1)} / 5`;

      const diffEl = document.createElement("span");
      diffEl.className = "rmp-difficulty";
      diffEl.title = "Avg difficulty (1–5)";
      diffEl.textContent = `Difficulty ${course.rmp_difficulty !== null && course.rmp_difficulty !== undefined ? course.rmp_difficulty.toFixed(1) : "—"}`;

      rmpBadge.append(ratingEl, diffEl);

      if (course.rmp_would_take_again_pct !== null && course.rmp_would_take_again_pct !== undefined && course.rmp_would_take_again_pct >= 0) {
        const wtaEl = document.createElement("span");
        wtaEl.className = "rmp-wta";
        wtaEl.title = "Would take again";
        wtaEl.textContent = `${Math.round(course.rmp_would_take_again_pct)}% again`;
        rmpBadge.appendChild(wtaEl);
      }

      if (course.rmp_url) {
        const rmpLink = document.createElement("a");
        rmpLink.className = "rmp-link";
        rmpLink.href = course.rmp_url;
        rmpLink.target = "_blank";
        rmpLink.rel = "noopener noreferrer";
        rmpLink.textContent = "RMP";
        rmpBadge.appendChild(rmpLink);
      }

      professorMeta.appendChild(rmpBadge);
    }

    professor.append(professorImage, professorMeta);

    article.append(code, courseTitle, meta, schedule, description, professor);
    recommendationsEl.appendChild(article);
  });
}

function parseDaysTimes(daysTimes) {
  if (!daysTimes) {
    return [];
  }

  const match = daysTimes.trim().match(/^([A-Za-z]+)\s+([\d:APMapm]+)\s*-\s*([\d:APMapm]+)$/);
  if (!match) {
    return [];
  }

  const daysText = match[1];
  const startTime = match[2];
  const endTime = match[3];
  const dayTokens = daysText.match(/Th|Tu|We|Fr|Sa|Su|Mo|M|T|W|R|F|S|U/gi) || [];
  const dayMap = {
    Mo: "Monday",
    Tu: "Tuesday",
    We: "Wednesday",
    Th: "Thursday",
    Fr: "Friday",
    Sa: "Saturday",
    Su: "Sunday",
    M: "Monday",
    T: "Tuesday",
    W: "Wednesday",
    R: "Thursday",
    F: "Friday",
    S: "Saturday",
    U: "Sunday",
  };

  return dayTokens
    .map((token) => dayMap[token.charAt(0).toUpperCase() + token.slice(1).toLowerCase()] || dayMap[token.toUpperCase()] || dayMap[token])
    .filter(Boolean)
    .map((day) => ({ day, startTime, endTime }));
}

function timeToMinutes(timeText) {
  if (!timeText) {
    return Number.POSITIVE_INFINITY;
  }

  const match = timeText.trim().match(/^(\d{1,2})(?::(\d{2}))?(AM|PM)$/i);
  if (!match) {
    return Number.POSITIVE_INFINITY;
  }

  let hours = parseInt(match[1], 10);
  const minutes = parseInt(match[2] || "0", 10);
  const period = match[3].toUpperCase();

  if (hours === 12) {
    hours = 0;
  }

  if (period === "PM") {
    hours += 12;
  }

  return hours * 60 + minutes;
}

function renderSchedule(courses = []) {
  const scheduleContainer = document.getElementById("schedule-container");
  const schedulePlaceholder = document.getElementById("schedule-placeholder");
  const scheduleGrid = document.getElementById("schedule-grid");

  // Filter courses that have schedule info
  const coursesWithSchedule = courses.filter((c) => c.days_times && c.days_times.trim());

  if (!coursesWithSchedule.length) {
    scheduleContainer.style.display = "none";
    schedulePlaceholder.style.display = "block";
    return;
  }

  scheduleContainer.style.display = "block";
  schedulePlaceholder.style.display = "none";
  scheduleGrid.innerHTML = "";

  // Create a simple schedule display: group courses by day
  const coursesByDay = {};

  coursesWithSchedule.forEach((course) => {
    const scheduleSlots = parseDaysTimes(course.days_times);
    scheduleSlots.forEach(({ day, startTime, endTime }) => {
      if (!coursesByDay[day]) coursesByDay[day] = [];
      coursesByDay[day].push({
        code: course.course_code,
        title: course.title,
        time: `${startTime} - ${endTime}`,
        instructor: course.instructor || "Instructor not available",
      });
    });
  });

  // Render schedule grid
  const daysOrder = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"];
  daysOrder.forEach((day) => {
    const dayDiv = document.createElement("div");
    dayDiv.className = "schedule-day";

    const dayHeader = document.createElement("h4");
    dayHeader.textContent = day;
    dayDiv.appendChild(dayHeader);

    if (coursesByDay[day]) {
      coursesByDay[day]
        .sort((left, right) => timeToMinutes(left.time.split(" - ")[0]) - timeToMinutes(right.time.split(" - ")[0]))
        .forEach((course) => {
        const courseDiv = document.createElement("div");
        courseDiv.className = "schedule-course";

        const courseCode = document.createElement("strong");
        courseCode.textContent = course.code;

        const courseTime = document.createElement("p");
        courseTime.className = "schedule-time";
        courseTime.textContent = `${course.time} | ${course.instructor}`;

        courseDiv.append(courseCode, courseTime);
        dayDiv.appendChild(courseDiv);
        });
    } else {
      const empty = document.createElement("p");
      empty.className = "schedule-empty";
      empty.textContent = "No classes";
      dayDiv.appendChild(empty);
    }

    scheduleGrid.appendChild(dayDiv);
  });
}

async function loadDegrees() {
  setStatus("Loading degree programs...");
  degreeSelect.innerHTML = "";

  try {
    const data = await fetchDegrees();
    const defaultOption = document.createElement("option");
    defaultOption.value = "";
    defaultOption.textContent = "Select a degree";
    degreeSelect.appendChild(defaultOption);

    data.degrees.forEach((degree) => {
      const option = document.createElement("option");
      option.value = degree.degree_name;
      option.textContent = degree.degree_name;
      degreeSelect.appendChild(option);
    });

    setStatus("Degree programs loaded.");
  } catch (error) {
    setStatus(`Failed to load degree programs: ${error.message}`, true);
    degreeSelect.innerHTML = "<option value=''>Could not load degrees</option>";
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  const major = degreeSelect.value.trim();
  if (!major) {
    setStatus("Please choose a degree program first.", true);
    return;
  }

  const maxUnitsInput = document.getElementById("max-units");
  const maxUnits = maxUnitsInput.value ? parseInt(maxUnitsInput.value, 10) : 12;

  const termSelect = document.getElementById("term-select");
  const term = termSelect.value || null;

  // Collect completed courses from manual textarea
  const completedRaw = document.getElementById("completed-courses").value || "";
  const completedCourses = completedRaw
    .split(/[\n,]+/)
    .map((s) => s.trim().toUpperCase())
    .filter(Boolean);

  // Collect transcript text
  const transcriptText = transcriptTextarea.value.trim() || null;

  // Blocked time windows: convert HH:MM → "H:MMAM/PM" for backend
  const blocked = blockedWindows.map((w) => ({
    day: w.day,
    start: formatTime24To12(w.start),
    end: formatTime24To12(w.end),
  }));

  submitBtn.disabled = true;
  setStatus("Generating recommendations…");

  const payload = {
    major,
    completed_courses: completedCourses,
    transcript_text: transcriptText,
    blocked_time_windows: blocked,
    interests: [],
    career_goals: [],
    prefer_light_workload: false,
    prefer_high_rated_professors: false,
    max_units_per_semester: maxUnits,
    term,
  };

  try {
    const data = await fetchRecommendations(payload);
    renderRecommendations(data.grouped_recommendations || [], data.recommendations || []);
    
    // Render schedule
    const allCourses = data.recommendations || [];
    renderSchedule(allCourses);
    
    // Display progress
    const progressContainer = document.getElementById("progress-container");
    const progressFill = document.getElementById("progress-fill");
    const progressText = document.getElementById("progress-text");
    
    if (data.total_units_selected !== undefined && data.total_units_required !== undefined) {
      const selected = data.total_units_selected;
      const required = data.total_units_required;

      progressContainer.style.display = "block";
      if (required > 0) {
        progressText.textContent = `${selected} / ${required} units toward degree`;
        progressFill.style.width = `${Math.min(100, (selected / required) * 100)}%`;
      } else {
        progressText.textContent = `${selected} units selected`;
        progressFill.style.width = "0%";
      }
    } else {
      progressContainer.style.display = "none";
    }
    
    explanationEl.textContent = data.explanation || "No explanation provided.";
    setStatus("Recommendations ready.");
  } catch (error) {
    renderRecommendations([]);
    renderSchedule([]);
    explanationEl.textContent = "Could not fetch recommendations.";
    setStatus(`Error: ${error.message}`, true);
    document.getElementById("progress-container").style.display = "none";
  } finally {
    submitBtn.disabled = false;
  }
});

loadDegrees();
