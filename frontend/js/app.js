// Conversational curriculum advisor frontend.
// Maintains chat history + rolling state, renders message bubbles, and
// re-renders the recommendation panel when the assistant returns advisor data.

const chatThread = document.getElementById("chat-thread");
const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
const chatStatus = document.getElementById("chat-status");
const chatStateDebug = document.getElementById("chat-state-debug");
const chatMaxUnitsInput = document.getElementById("chat-max-units");
const chatBlockedToggle = document.getElementById("chat-blocked-toggle");
const chatBlockedDetails = document.getElementById("chat-blocked-windows");
const chatResetButton = document.getElementById("chat-reset");
const sendButton = document.getElementById("chat-send");
const resultsPanel = document.getElementById("results-panel");
const explanationEl = document.getElementById("explanation");
const recommendationsEl = document.getElementById("recommendations");
const prereqBlockedSection = document.getElementById("prereq-blocked-section");
const prereqBlockedList = document.getElementById("prereq-blocked-list");
const professorRmpCache = new Map();

const conversationHistory = [];
let conversationState = {
  major: null,
  term: null,
  completed_courses: [],
  preferences_text: null,
  prefer_high_rated_professors: false,
  prefer_light_workload: false,
  max_units_per_semester: 9,
  blocked_time_windows: [],
};

const blockedWindows = [];

function setChatStatus(message, kind = "neutral") {
  chatStatus.textContent = message;
  chatStatus.classList.remove("error", "success", "info");
  if (kind && kind !== "neutral") {
    chatStatus.classList.add(kind);
  }
}

function renderChatStateDebug() {
  chatStateDebug.textContent = JSON.stringify(conversationState, null, 2);
}

function appendMessage(role, content, meta = null) {
  const wrapper = document.createElement("div");
  wrapper.className = `chat-message chat-message-${role}`;

  const bubble = document.createElement("div");
  bubble.className = "chat-bubble";
  bubble.textContent = content;
  wrapper.appendChild(bubble);

  if (meta) {
    const metaEl = document.createElement("p");
    metaEl.className = "chat-message-meta";
    metaEl.textContent = meta;
    wrapper.appendChild(metaEl);
  }

  chatThread.appendChild(wrapper);
  chatThread.scrollTop = chatThread.scrollHeight;
}

function appendThinkingIndicator() {
  const wrapper = document.createElement("div");
  wrapper.className = "chat-message chat-message-assistant chat-thinking";
  wrapper.id = "chat-thinking-indicator";

  const bubble = document.createElement("div");
  bubble.className = "chat-bubble chat-bubble-thinking";
  bubble.textContent = "Thinking…";

  wrapper.appendChild(bubble);
  chatThread.appendChild(wrapper);
  chatThread.scrollTop = chatThread.scrollHeight;
}

function removeThinkingIndicator() {
  const node = document.getElementById("chat-thinking-indicator");
  if (node) {
    node.remove();
  }
}

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
    setChatStatus("Blocked window: end time must be after start time.", "error");
    return;
  }
  blockedWindows.push({ day, start, end });
  renderBlockedWindows();
  setChatStatus(`Added blocked window. (${blockedWindows.length} total.)`, "info");
});

chatBlockedToggle.addEventListener("click", () => {
  chatBlockedDetails.open = !chatBlockedDetails.open;
});

chatResetButton.addEventListener("click", () => {
  conversationHistory.length = 0;
  conversationState = {
    major: null,
    term: null,
    completed_courses: [],
    preferences_text: null,
    prefer_high_rated_professors: false,
    prefer_light_workload: false,
    max_units_per_semester: parseInt(chatMaxUnitsInput.value, 10) || 9,
    blocked_time_windows: [],
  };
  blockedWindows.length = 0;
  renderBlockedWindows();
  chatThread.innerHTML = "";
  appendMessage(
    "assistant",
    "Started a new conversation. What major and term are you planning?",
  );
  resultsPanel.hidden = true;
  renderChatStateDebug();
  setChatStatus("Ready.");
});

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
  if (/^https?:\/\//i.test(value) || value.startsWith("data:image/")) {
    return value;
  }
  if (value.startsWith("/") && typeof API_BASE_URL === "string" && API_BASE_URL) {
    return `${API_BASE_URL}${value}`;
  }
  return null;
}

function getPillTone(value, kind) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "neutral";
  }
  const numericValue = Number(value);
  if (kind === "difficulty") {
    if (numericValue >= 3.8) return "red";
    if (numericValue >= 2.8) return "yellow";
    return "green";
  }
  if (kind === "sentiment") {
    if (numericValue >= 0.7) return "green";
    if (numericValue >= 0.45) return "yellow";
    return "red";
  }
  if (kind === "wta") {
    if (numericValue >= 80) return "green";
    if (numericValue >= 60) return "yellow";
    return "red";
  }
  if (numericValue >= 4.0) return "green";
  if (numericValue >= 3.0) return "yellow";
  return "red";
}

function applyPillTone(element, tone) {
  element.classList.add(`pill-tone-${tone}`);
}

function normalizeProfessorKey(name) {
  return (name || "").trim().toLowerCase();
}

async function getProfessorRmpData(course) {
  const professorName = course.professor_name || course.instructor;
  const cacheKey = normalizeProfessorKey(professorName);
  if (!cacheKey) {
    return null;
  }
  if (professorRmpCache.has(cacheKey)) {
    return professorRmpCache.get(cacheKey);
  }
  try {
    const rating = await fetchProfessorRating(professorName);
    professorRmpCache.set(cacheKey, rating);
    return rating;
  } catch {
    professorRmpCache.set(cacheKey, null);
    return null;
  }
}

async function renderRecommendations(groups, fallbackCourses = []) {
  recommendationsEl.innerHTML = "";

  let allCourses = [];
  if (groups && groups.length) {
    groups.forEach((group) => {
      group.courses.forEach((course) => {
        allCourses.push({ ...course, group_name: group.group_name });
      });
    });
  }
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

  const enrichedCourses = await Promise.all(
    allCourses.map(async (course) => {
      const needsRmpData =
        course.rmp_rating === null || course.rmp_rating === undefined ||
        course.rmp_difficulty === null || course.rmp_difficulty === undefined ||
        course.rmp_would_take_again_pct === null || course.rmp_would_take_again_pct === undefined ||
        !course.rmp_top_tag;
      if (!needsRmpData) return course;

      const rmpData = await getProfessorRmpData(course);
      if (!rmpData) return course;
      return {
        ...course,
        rmp_rating: course.rmp_rating ?? rmpData.rating,
        rmp_difficulty: course.rmp_difficulty ?? rmpData.difficulty,
        rmp_would_take_again_pct: course.rmp_would_take_again_pct ?? rmpData.would_take_again_pct,
        rmp_url: course.rmp_url ?? rmpData.rmp_url,
        rmp_num_ratings: course.rmp_num_ratings ?? rmpData.num_ratings,
        rmp_top_tag: course.rmp_top_tag ?? rmpData.top_tag,
        rmp_top_tag_count: course.rmp_top_tag_count ?? rmpData.top_tag_count,
        rmp_top_tag_tone: course.rmp_top_tag_tone ?? rmpData.top_tag_tone,
      };
    }),
  );

  enrichedCourses.forEach((course) => {
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

    if (course.rationale) {
      const rationale = document.createElement("p");
      rationale.className = "course-rationale";
      rationale.textContent = course.rationale;
      article.append(code, courseTitle, meta, rationale);
    } else {
      article.append(code, courseTitle, meta);
    }

    if (course.prerequisite_text || (course.prerequisite_satisfied_by && course.prerequisite_satisfied_by.length)) {
      const prereq = document.createElement("p");
      prereq.className = "course-prerequisite";
      const satisfiedClause =
        course.prerequisite_satisfied_by && course.prerequisite_satisfied_by.length
          ? ` (you've completed ${course.prerequisite_satisfied_by.join(", ")})`
          : "";
      prereq.textContent = `Prereq: ${course.prerequisite_text || "—"}${satisfiedClause}`;
      article.appendChild(prereq);
    }

    const schedule = document.createElement("p");
    schedule.className = "course-schedule";
    schedule.textContent = course.days_times || "Time not available";
    article.appendChild(schedule);

    const description = document.createElement("p");
    description.className = "course-description";
    description.textContent = course.description || "Course description not available.";
    article.appendChild(description);

    const professor = document.createElement("div");
    professor.className = "professor-card";

    const professorVisual = document.createElement("div");
    professorVisual.className = "professor-visual";

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

    const professorPills = document.createElement("div");
    professorPills.className = "professor-pill-row";

    const sentimentPill = document.createElement("div");
    sentimentPill.className = "professor-rating-pill professor-rating-pill-sentiment";
    if (course.professor_sentiment_score !== null && course.professor_sentiment_score !== undefined) {
      sentimentPill.title = "Sentiment score derived from review text";
      sentimentPill.textContent = `Sentiment ${(course.professor_sentiment_score * 100).toFixed(0)}%`;
      applyPillTone(sentimentPill, getPillTone(course.professor_sentiment_score, "sentiment"));
    } else {
      sentimentPill.title = "No sentiment score available for this professor";
      sentimentPill.textContent = "Sentiment n/a";
      applyPillTone(sentimentPill, "neutral");
    }
    professorPills.append(sentimentPill);

    if (course.rmp_top_tag) {
      const tagPill = document.createElement("div");
      tagPill.className = "professor-rating-pill professor-rating-pill-tag";
      const tagCount = Number.isFinite(Number(course.rmp_top_tag_count)) ? Number(course.rmp_top_tag_count) : null;
      tagPill.title = tagCount && tagCount > 1
        ? `Most repeated tag across reviews: ${course.rmp_top_tag} (${tagCount} reviews)`
        : `Most repeated tag across reviews: ${course.rmp_top_tag}`;
      tagPill.textContent = tagCount && tagCount > 1
        ? `Top tag: ${course.rmp_top_tag} (${tagCount})`
        : `Top tag: ${course.rmp_top_tag}`;
      applyPillTone(tagPill, course.rmp_top_tag_tone || "neutral");
      professorPills.append(tagPill);
    }

    professorVisual.append(professorImage);

    if (course.rmp_rating !== null && course.rmp_rating !== undefined) {
      const rmpBadge = document.createElement("div");
      rmpBadge.className = "rmp-badge";

      const ratingEl = document.createElement("span");
      ratingEl.className = "rmp-rating";
      ratingEl.title = `Based on ${course.rmp_num_ratings ?? "?"} ratings`;
      ratingEl.textContent = `${course.rmp_rating.toFixed(1)} / 5`;
      applyPillTone(ratingEl, getPillTone(course.rmp_rating, "rating"));

      const diffEl = document.createElement("span");
      diffEl.className = "rmp-difficulty";
      diffEl.title = "Avg difficulty (1–5)";
      diffEl.textContent = `Difficulty ${
        course.rmp_difficulty !== null && course.rmp_difficulty !== undefined
          ? course.rmp_difficulty.toFixed(1)
          : "—"
      }`;
      applyPillTone(diffEl, getPillTone(course.rmp_difficulty, "difficulty"));

      rmpBadge.append(ratingEl, diffEl);

      if (course.rmp_would_take_again_pct !== null && course.rmp_would_take_again_pct !== undefined && course.rmp_would_take_again_pct >= 0) {
        const wtaEl = document.createElement("span");
        wtaEl.className = "rmp-wta";
        wtaEl.title = "Would take again";
        wtaEl.textContent = `${Math.round(course.rmp_would_take_again_pct)}% again`;
        applyPillTone(wtaEl, getPillTone(course.rmp_would_take_again_pct, "wta"));
        rmpBadge.appendChild(wtaEl);
      }
      professorPills.appendChild(rmpBadge);
    }

    professorMeta.appendChild(professorPills);

    if (course.professor_review_summary) {
      const summaryEl = document.createElement("p");
      summaryEl.className = "professor-summary";
      summaryEl.textContent = course.professor_review_summary;
      professorMeta.appendChild(summaryEl);
    }

    professor.append(professorVisual, professorMeta);
    article.appendChild(professor);
    recommendationsEl.appendChild(article);
  });
}

function renderPrereqBlocked(blockedCourses = []) {
  if (!blockedCourses.length) {
    prereqBlockedSection.hidden = true;
    prereqBlockedList.innerHTML = "";
    return;
  }
  prereqBlockedSection.hidden = false;
  prereqBlockedList.innerHTML = "";
  blockedCourses.forEach((blocked) => {
    const item = document.createElement("li");
    item.className = "prereq-blocked-item";
    const code = document.createElement("strong");
    code.textContent = blocked.course_code;
    const title = document.createElement("span");
    title.className = "prereq-blocked-title";
    title.textContent = blocked.title ? ` — ${blocked.title}` : "";
    const reason = document.createElement("span");
    reason.className = "prereq-blocked-reason";
    reason.textContent = blocked.unmet_prerequisites
      ? ` · needs ${blocked.unmet_prerequisites}`
      : "";
    item.append(code, title, reason);
    prereqBlockedList.appendChild(item);
  });
}

function parseDaysTimes(daysTimes) {
  if (!daysTimes) return [];
  const match = daysTimes.trim().match(/^([A-Za-z]+)\s+([\d:APMapm]+)\s*-\s*([\d:APMapm]+)$/);
  if (!match) return [];
  const daysText = match[1];
  const startTime = match[2];
  const endTime = match[3];
  const dayTokens = daysText.match(/Th|Tu|We|Fr|Sa|Su|Mo|M|T|W|R|F|S|U/gi) || [];
  const dayMap = {
    Mo: "Monday", Tu: "Tuesday", We: "Wednesday", Th: "Thursday",
    Fr: "Friday", Sa: "Saturday", Su: "Sunday",
    M: "Monday", T: "Tuesday", W: "Wednesday", R: "Thursday",
    F: "Friday", S: "Saturday", U: "Sunday",
  };
  return dayTokens
    .map((token) => dayMap[token.charAt(0).toUpperCase() + token.slice(1).toLowerCase()] || dayMap[token.toUpperCase()] || dayMap[token])
    .filter(Boolean)
    .map((day) => ({ day, startTime, endTime }));
}

function timeToMinutes(timeText) {
  if (!timeText) return Number.POSITIVE_INFINITY;
  const match = timeText.trim().match(/^(\d{1,2})(?::(\d{2}))?(AM|PM)$/i);
  if (!match) return Number.POSITIVE_INFINITY;
  let hours = parseInt(match[1], 10);
  const minutes = parseInt(match[2] || "0", 10);
  const period = match[3].toUpperCase();
  if (hours === 12) hours = 0;
  if (period === "PM") hours += 12;
  return hours * 60 + minutes;
}

function renderSchedule(courses = []) {
  const scheduleContainer = document.getElementById("schedule-container");
  const schedulePlaceholder = document.getElementById("schedule-placeholder");
  const scheduleGrid = document.getElementById("schedule-grid");
  const coursesWithSchedule = courses.filter((c) => c.days_times && c.days_times.trim());

  if (!coursesWithSchedule.length) {
    scheduleContainer.style.display = "none";
    schedulePlaceholder.style.display = "block";
    return;
  }

  scheduleContainer.style.display = "block";
  schedulePlaceholder.style.display = "none";
  scheduleGrid.innerHTML = "";

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

function renderProgress(advisor) {
  const progressContainer = document.getElementById("progress-container");
  const progressFill = document.getElementById("progress-fill");
  const progressText = document.getElementById("progress-text");
  if (!advisor) {
    progressContainer.style.display = "none";
    return;
  }
  const selected = advisor.total_units_selected ?? 0;
  const required = advisor.total_units_required ?? 0;
  progressContainer.style.display = "block";
  if (required > 0) {
    progressText.textContent = `${selected} / ${required} units toward degree`;
    progressFill.style.width = `${Math.min(100, (selected / required) * 100)}%`;
  } else {
    progressText.textContent = `${selected} units selected`;
    progressFill.style.width = "0%";
  }
}

async function handleAdvisorPayload(advisor) {
  if (!advisor) {
    resultsPanel.hidden = true;
    return;
  }
  resultsPanel.hidden = false;
  await renderRecommendations(advisor.grouped_recommendations || [], advisor.recommendations || []);
  renderSchedule(advisor.recommendations || []);
  renderProgress(advisor);
  renderPrereqBlocked(advisor.prerequisite_blocked_courses || []);
  explanationEl.textContent = advisor.explanation || "No explanation provided.";
}

function buildOutgoingState() {
  const blocked = blockedWindows.map((w) => ({
    day: w.day,
    start: formatTime24To12(w.start),
    end: formatTime24To12(w.end),
  }));
  const maxUnits = parseInt(chatMaxUnitsInput.value, 10);
  return {
    ...conversationState,
    max_units_per_semester: Number.isFinite(maxUnits) && maxUnits > 0 ? maxUnits : conversationState.max_units_per_semester,
    blocked_time_windows: blocked,
  };
}

function applyResponseState(state) {
  if (!state) return;
  conversationState = {
    major: state.major ?? conversationState.major,
    term: state.term ?? conversationState.term,
    completed_courses: Array.isArray(state.completed_courses) ? state.completed_courses : conversationState.completed_courses,
    preferences_text: state.preferences_text ?? conversationState.preferences_text,
    prefer_high_rated_professors: !!state.prefer_high_rated_professors,
    prefer_light_workload: !!state.prefer_light_workload,
    max_units_per_semester: state.max_units_per_semester ?? conversationState.max_units_per_semester,
    blocked_time_windows: Array.isArray(state.blocked_time_windows) ? state.blocked_time_windows : conversationState.blocked_time_windows,
  };
  renderChatStateDebug();
}

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = chatInput.value.trim();
  if (!message) return;

  appendMessage("user", message);
  conversationHistory.push({ role: "user", content: message });
  chatInput.value = "";
  sendButton.disabled = true;
  appendThinkingIndicator();
  setChatStatus("Sending to advisor…", "info");

  try {
    const payload = {
      message,
      state: buildOutgoingState(),
      history: conversationHistory.slice(-8),
    };
    const data = await sendChatMessage(payload);
    removeThinkingIndicator();

    appendMessage("assistant", data.reply || "(no reply)");
    conversationHistory.push({ role: "assistant", content: data.reply || "" });

    applyResponseState(data.state);
    await handleAdvisorPayload(data.advisor);

    const sourceLabel =
      data.intent_source === "llm" ? "intent: LLM" : "intent: regex fallback";
    const rationaleLabel =
      data.rationale_source === "llm"
        ? " · rationales: LLM"
        : data.rationale_source === "template"
          ? " · rationales: template"
          : data.rationale_source === "llm+template"
            ? " · rationales: LLM + template"
            : "";
    setChatStatus(`Done (${sourceLabel}${rationaleLabel}).`, "success");

    if (data.missing_required_fields && data.missing_required_fields.length) {
      const missing = data.missing_required_fields.join(", ");
      setChatStatus(`Need ${missing} to recommend courses.`, "info");
    }
  } catch (error) {
    removeThinkingIndicator();
    appendMessage("assistant", `I hit an error talking to the advisor: ${error.message}`);
    setChatStatus(`Error: ${error.message}`, "error");
  } finally {
    sendButton.disabled = false;
    chatInput.focus();
  }
});

renderChatStateDebug();
