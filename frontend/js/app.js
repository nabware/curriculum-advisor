// Curriculum Advisor -- app.js
// Wired to the SFSU-branded index.html.
// Maintains chat history + rolling state, renders message bubbles,
// drives tab switching, and updates sidebar stats on each advisor response.

const chatThread       = document.getElementById("chat-thread");
const chatForm         = document.getElementById("chat-form");
const chatInput        = document.getElementById("chat-input");
const chatStatus       = document.getElementById("chat-status");
const chatStateDebug   = document.getElementById("chat-state-debug");
const chatMaxUnitsInput= document.getElementById("chat-max-units");
const chatBlockedToggle= document.getElementById("chat-blocked-toggle");
const chatBlockedDetails=document.getElementById("chat-blocked-windows");
const chatResetButton  = document.getElementById("chat-reset");
const sendButton       = document.getElementById("chat-send");

const recommendationsEl     = document.getElementById("recommendations");
const prereqBlockedSection  = document.getElementById("prereq-blocked-section");
const prereqBlockedList     = document.getElementById("prereq-blocked-list");
const explanationEl         = document.getElementById("explanation");
const progressContainer     = document.getElementById("progress-container");
const progressFill          = document.getElementById("progress-fill");
const progressText          = document.getElementById("progress-text");
const resultsUnitsBadge     = document.getElementById("results-units-badge");
const scheduleBadge         = document.getElementById("schedule-badge");
const chatTermBadge         = document.getElementById("chat-term-badge");

const stMajor     = document.getElementById("st-major");
const stTerm      = document.getElementById("st-term");
const stCompleted = document.getElementById("st-completed");
const stPrefs     = document.getElementById("st-prefs");
const stEligible  = document.getElementById("st-eligible");
const stBlocked   = document.getElementById("st-blocked");
const stUnitsSel  = document.getElementById("st-units-sel");
const stUnitsReq  = document.getElementById("st-units-req");

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

const navBtns  = document.querySelectorAll(".nav-btn[data-tab]");
const tabPanels= document.querySelectorAll(".tab-panel");

const mainGrid = document.querySelector(".main-grid");

navBtns.forEach(btn => {
  btn.addEventListener("click", () => {
    navBtns.forEach(b  => b.classList.remove("active"));
    tabPanels.forEach(p=> p.classList.add("hidden"));
    btn.classList.add("active");
    const panel = document.getElementById(`tab-${btn.dataset.tab}`);
    if (panel) panel.classList.remove("hidden");

    const shell = document.querySelector(".page-shell");
    if (mainGrid) {
      if (btn.dataset.tab === "chat") {
        mainGrid.classList.remove("full-width");
        if (shell) shell.style.maxWidth = "";
      } else {
        mainGrid.classList.add("full-width");
        if (shell) shell.style.maxWidth = "1400px";
      }
    }
  });
});

document.querySelectorAll(".chip").forEach(chip => {
  chip.addEventListener("click", () => {
    chatInput.value = chip.textContent.trim();
    chatInput.focus();
    document.querySelector(".nav-btn[data-tab='chat']").click();
  });
});

function updateSidebar(advisor) {
  setStateEl(stMajor,     conversationState.major,            "not set");
  setStateEl(stTerm,      conversationState.term,             "not set");
  setStateEl(stCompleted,
    conversationState.completed_courses && conversationState.completed_courses.length
      ? conversationState.completed_courses.join(", ")
      : null,
    "none");
  setStateEl(stPrefs, conversationState.preferences_text, "not set");

  if (advisor) {
    const eligible = advisor.recommendations ? advisor.recommendations.length : 0;
    const blocked  = advisor.prerequisite_blocked_courses
      ? advisor.prerequisite_blocked_courses.length : 0;
    const sel      = advisor.total_units_selected  || 0;
    const req      = advisor.total_units_required  || 0;

    stEligible.textContent  = eligible;
    stBlocked.textContent   = blocked;
    stUnitsSel.textContent  = sel;
    stUnitsReq.textContent  = req || "--";

    if (chatTermBadge && conversationState.term) {
      chatTermBadge.textContent = conversationState.term;
    }
    if (resultsUnitsBadge) {
      resultsUnitsBadge.textContent = `${sel} units selected`;
    }
    if (scheduleBadge && conversationState.term) {
      scheduleBadge.textContent =
        `${conversationState.term} . ${eligible} course${eligible !== 1 ? "s" : ""}`;
    }
  }
}

function setStateEl(el, value, emptyLabel) {
  if (!el) return;
  if (value) {
    el.textContent = value;
    el.className = "state-val set";
  } else {
    el.textContent = emptyLabel;
    el.className = "state-val unset";
  }
}

function setChatStatus(message, kind = "neutral") {
  chatStatus.textContent = message;
  chatStatus.classList.remove("error", "success", "info");
  if (kind && kind !== "neutral") chatStatus.classList.add(kind);
}

function renderChatStateDebug() {
  if (chatStateDebug) {
    chatStateDebug.textContent = JSON.stringify(conversationState, null, 2);
  }
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
  bubble.textContent = "Thinking...";
  wrapper.appendChild(bubble);
  chatThread.appendChild(wrapper);
  chatThread.scrollTop = chatThread.scrollHeight;
}

function removeThinkingIndicator() {
  const node = document.getElementById("chat-thinking-indicator");
  if (node) node.remove();
}

function formatTime24To12(hhmm) {
  const [hStr, mStr] = hhmm.split(":");
  let h = parseInt(hStr, 10);
  const m = mStr || "00";
  const period = h >= 12 ? "PM" : "AM";
  if (h === 0) h = 12; else if (h > 12) h -= 12;
  return `${h}:${m}${period}`;
}

function renderBlockedWindows() {
  const list = document.getElementById("blocked-windows-list");
  list.innerHTML = "";
  blockedWindows.forEach((w, idx) => {
    const chip = document.createElement("span");
    chip.className = "blocked-chip";
    chip.textContent = `${w.day} ${formatTime24To12(w.start)} - ${formatTime24To12(w.end)}`;
    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "blocked-chip-remove";
    removeBtn.setAttribute("aria-label", `Remove ${chip.textContent}`);
    removeBtn.textContent = "x";
    removeBtn.addEventListener("click", () => {
      blockedWindows.splice(idx, 1);
      renderBlockedWindows();
    });
    chip.appendChild(removeBtn);
    list.appendChild(chip);
  });
}

document.getElementById("add-blocked-btn").addEventListener("click", () => {
  const day   = document.getElementById("blocked-day").value;
  const start = document.getElementById("blocked-start").value;
  const end   = document.getElementById("blocked-end").value;
  if (!start || !end || start >= end) {
    setChatStatus("End time must be after start time.", "error");
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
    major: null, term: null, completed_courses: [],
    preferences_text: null,
    prefer_high_rated_professors: false,
    prefer_light_workload: false,
    max_units_per_semester: parseInt(chatMaxUnitsInput.value, 10) || 9,
    blocked_time_windows: [],
  };
  blockedWindows.length = 0;
  renderBlockedWindows();
  chatThread.innerHTML = "";
  appendMessage("assistant",
    "Hi, Gator! 🐊 Started a new conversation. What major and term are you planning?");
  recommendationsEl.innerHTML = '<p class="empty-state">No recommendations yet -- start a chat.</p>';
  prereqBlockedSection.hidden = true;
  progressContainer.style.display = "none";
  renderChatStateDebug();
  updateSidebar(null);
  setChatStatus("Ready.");
  document.querySelector(".nav-btn[data-tab='chat']").click();
});

function hashString(value) {
  let hash = 0;
  for (let i = 0; i < value.length; i++) hash = (hash * 31 + value.charCodeAt(i)) >>> 0;
  return hash;
}

function buildAvatarDataUrl(name) {
  const safeName = (name || "Professor").trim() || "Professor";
  const initials = safeName.split(/\s+/).slice(0, 2)
    .map(p => p.charAt(0).toUpperCase()).join("") || "P";
  const palette = ["#231161", "#3a1f8a", "#5b3ab5", "#7a5a00", "#1a7a4a"];
  const color = palette[hashString(safeName) % palette.length];
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="120" height="120" viewBox="0 0 120 120">
    <rect width="120" height="120" rx="60" fill="${color}"/>
    <text x="60" y="69" text-anchor="middle" font-family="Source Sans 3,Arial,sans-serif"
          font-size="40" font-weight="700" fill="#fff">${initials}</text></svg>`;
  return `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg.trim())}`;
}

function getRenderableProfessorImageUrl(imageUrl) {
  const value = (imageUrl || "").trim();
  if (!value) return null;
  if (/^https?:\/\//i.test(value) || value.startsWith("data:image/")) return value;
  if (value.startsWith("/") && typeof API_BASE_URL === "string" && API_BASE_URL)
    return `${API_BASE_URL}${value}`;
  return null;
}

function getPillTone(value, kind) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "neutral";
  const v = Number(value);
  if (kind === "difficulty") return v >= 3.8 ? "red" : v >= 2.8 ? "yellow" : "green";
  if (kind === "sentiment")  return v >= 0.7  ? "green" : v >= 0.45 ? "yellow" : "red";
  if (kind === "wta")        return v >= 80   ? "green" : v >= 60   ? "yellow" : "red";
  return v >= 4.0 ? "green" : v >= 3.0 ? "yellow" : "red";
}

function applyPillTone(el, tone) {
  el.classList.add(`pill-tone-${tone}`);
}

function normalizeProfessorKey(name) {
  return (name || "").trim().toLowerCase();
}

async function getProfessorRmpData(course) {
  const professorName = course.professor_name || course.instructor;
  const cacheKey = normalizeProfessorKey(professorName);
  if (!cacheKey) return null;
  if (professorRmpCache.has(cacheKey)) return professorRmpCache.get(cacheKey);
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
    groups.forEach(group => {
      group.courses.forEach(course => allCourses.push({ ...course, group_name: group.group_name }));
    });
  }
  if (!allCourses.length && fallbackCourses.length) allCourses = fallbackCourses;

  if (!allCourses.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "No courses matched yet.";
    recommendationsEl.appendChild(empty);
    return;
  }

  const enriched = await Promise.all(allCourses.map(async course => {
    const needsRmp =
      course.rmp_rating == null || course.rmp_difficulty == null ||
      course.rmp_would_take_again_pct == null || !course.rmp_top_tag;
    if (!needsRmp) return course;
    const rmp = await getProfessorRmpData(course);
    if (!rmp) return course;
    return {
      ...course,
      rmp_rating:              course.rmp_rating              ?? rmp.rating,
      rmp_difficulty:          course.rmp_difficulty          ?? rmp.difficulty,
      rmp_would_take_again_pct:course.rmp_would_take_again_pct?? rmp.would_take_again_pct,
      rmp_url:                 course.rmp_url                 ?? rmp.rmp_url,
      rmp_num_ratings:         course.rmp_num_ratings         ?? rmp.num_ratings,
      rmp_top_tag:             course.rmp_top_tag             ?? rmp.top_tag,
      rmp_top_tag_count:       course.rmp_top_tag_count       ?? rmp.top_tag_count,
      rmp_top_tag_tone:        course.rmp_top_tag_tone        ?? rmp.top_tag_tone,
    };
  }));

  const byGroup = [];
  const groupOrder = [];
  enriched.forEach(course => {
    const gn = course.group_name || "Other";
    if (!groupOrder.includes(gn)) groupOrder.push(gn);
  });

  groupOrder.forEach(gn => {
    const header = document.createElement("div");
    header.className = "group-label";
    header.textContent = gn;
    recommendationsEl.appendChild(header);

    const grid = document.createElement("div");
    grid.className = "course-grid";
    recommendationsEl.appendChild(grid);

    enriched.filter(c => (c.group_name || "Other") === gn).forEach(course => {
      grid.appendChild(buildCourseCard(course));
    });
  });
}

function buildCourseCard(course) {
  const article = document.createElement("article");
  article.className = "recommendation-card";

  const code = document.createElement("p");
  code.className = "course-code";
  code.textContent = course.course_code;

  const title = document.createElement("h4");
  title.textContent = course.title;

  const meta = document.createElement("p");
  meta.className = "course-meta";
  meta.textContent = `${course.units != null ? course.units + " units" : "Units TBD"}`;

  const tags = document.createElement("div");
  tags.className = "course-tags";

  if (course.units != null) {
    const t = document.createElement("span");
    t.className = "tag tag-units";
    t.textContent = `${course.units} units`;
    tags.appendChild(t);
  }
  if (course.days_times) {
    const t = document.createElement("span");
    t.className = "tag tag-time";
    t.textContent = course.days_times;
    tags.appendChild(t);
  }
  if (course.prerequisite_satisfied_by && course.prerequisite_satisfied_by.length) {
    const t = document.createElement("span");
    t.className = "tag tag-prereq";
    t.textContent = "v prereqs met";
    tags.appendChild(t);
  }

  article.append(code, title, tags);

  if (course.prerequisite_text) {
    const pre = document.createElement("p");
    pre.className = "course-prerequisite";
    const satisfied = course.prerequisite_satisfied_by && course.prerequisite_satisfied_by.length
      ? ` (completed: ${course.prerequisite_satisfied_by.join(", ")})` : "";
    pre.textContent = `Prereq: ${course.prerequisite_text}${satisfied}`;
    article.appendChild(pre);
  }

  if (course.description) {
    const desc = document.createElement("p");
    desc.className = "course-description";
    desc.textContent = course.description;
    article.appendChild(desc);
  }

  if (course.rationale) {
    const rat = document.createElement("p");
    rat.className = "course-rationale";
    rat.textContent = course.rationale;
    article.appendChild(rat);
  }

  const profCard = document.createElement("div");
  profCard.className = "professor-card";

  const profVisual = document.createElement("div");
  profVisual.className = "professor-visual";

  const img = document.createElement("img");
  img.className = "professor-image";
  img.alt = course.professor_name || course.instructor || "Professor";
  const fallback = buildAvatarDataUrl(course.professor_name || course.instructor);
  img.src = getRenderableProfessorImageUrl(course.professor_image_url) || fallback;
  img.addEventListener("error", () => { img.src = fallback; }, { once: true });
  profVisual.appendChild(img);

  const profMeta = document.createElement("div");
  profMeta.className = "professor-meta";

  const profName = document.createElement("p");
  profName.className = "professor-name";
  profName.textContent = course.professor_name || course.instructor || "Professor not available";
  profMeta.appendChild(profName);

  const pillRow = document.createElement("div");
  pillRow.className = "professor-pill-row";

  const sentPill = document.createElement("div");
  sentPill.className = "professor-rating-pill professor-rating-pill-sentiment";
  if (course.professor_sentiment_score != null) {
    sentPill.title = "Sentiment score from review text";
    sentPill.textContent = `Sentiment ${(course.professor_sentiment_score * 100).toFixed(0)}%`;
    applyPillTone(sentPill, getPillTone(course.professor_sentiment_score, "sentiment"));
  } else {
    sentPill.textContent = "Sentiment n/a";
    applyPillTone(sentPill, "neutral");
  }
  pillRow.appendChild(sentPill);

  if (course.rmp_top_tag) {
    const tagPill = document.createElement("div");
    tagPill.className = "professor-rating-pill professor-rating-pill-tag";
    const cnt = Number.isFinite(Number(course.rmp_top_tag_count))
      ? Number(course.rmp_top_tag_count) : null;
    tagPill.textContent = cnt && cnt > 1
      ? `Top tag: ${course.rmp_top_tag} (${cnt})`
      : `Top tag: ${course.rmp_top_tag}`;
    applyPillTone(tagPill, course.rmp_top_tag_tone || "neutral");
    pillRow.appendChild(tagPill);
  }

  if (course.rmp_rating != null) {
    const rmpBadge = document.createElement("div");
    rmpBadge.className = "rmp-badge";

    const ratingEl = document.createElement("span");
    ratingEl.className = "rmp-rating";
    ratingEl.title = `Based on ${course.rmp_num_ratings ?? "?"} ratings`;
    ratingEl.textContent = `${course.rmp_rating.toFixed(1)} / 5`;
    applyPillTone(ratingEl, getPillTone(course.rmp_rating, "rating"));

    const diffEl = document.createElement("span");
    diffEl.className = "rmp-difficulty";
    diffEl.title = "Avg difficulty (1-5)";
    diffEl.textContent = `Difficulty ${course.rmp_difficulty != null ? course.rmp_difficulty.toFixed(1) : "--"}`;
    applyPillTone(diffEl, getPillTone(course.rmp_difficulty, "difficulty"));

    rmpBadge.append(ratingEl, diffEl);

    if (course.rmp_would_take_again_pct != null && course.rmp_would_take_again_pct >= 0) {
      const wtaEl = document.createElement("span");
      wtaEl.className = "rmp-wta";
      wtaEl.title = "Would take again";
      wtaEl.textContent = `${Math.round(course.rmp_would_take_again_pct)}% again`;
      applyPillTone(wtaEl, getPillTone(course.rmp_would_take_again_pct, "wta"));
      rmpBadge.appendChild(wtaEl);
    }

    if (course.rmp_url) {
      const rmpLink = document.createElement("a");
      rmpLink.className = "rmp-link";
      rmpLink.href = course.rmp_url;
      rmpLink.target = "_blank";
      rmpLink.rel = "noopener noreferrer";
      rmpLink.textContent = "RMP ->";
      rmpBadge.appendChild(rmpLink);
    }

    pillRow.appendChild(rmpBadge);
  }

  profMeta.appendChild(pillRow);

  if (course.professor_review_summary) {
    const summaryEl = document.createElement("p");
    summaryEl.className = "professor-summary";
    summaryEl.textContent = course.professor_review_summary;
    profMeta.appendChild(summaryEl);
  }

  profCard.append(profVisual, profMeta);
  article.appendChild(profCard);

  return article;
}

function renderPrereqBlocked(blockedCourses = []) {
  if (!blockedCourses.length) {
    prereqBlockedSection.hidden = true;
    prereqBlockedList.innerHTML = "";
    return;
  }
  prereqBlockedSection.hidden = false;
  prereqBlockedList.innerHTML = "";
  blockedCourses.forEach(blocked => {
    const item = document.createElement("li");
    item.className = "prereq-blocked-item";
    const code = document.createElement("strong");
    code.textContent = blocked.course_code;
    const titleEl = document.createElement("span");
    titleEl.className = "prereq-blocked-title";
    titleEl.textContent = blocked.title ? ` -- ${blocked.title}` : "";
    const reason = document.createElement("span");
    reason.className = "prereq-blocked-reason";
    reason.textContent = blocked.unmet_prerequisites
      ? ` . needs ${blocked.unmet_prerequisites}` : "";
    item.append(code, titleEl, reason);
    prereqBlockedList.appendChild(item);
  });
}

function parseDaysTimes(daysTimes) {
  if (!daysTimes) return [];
  const match = daysTimes.trim().match(
    /^([A-Za-z]+)\s+([\d:APMapm]+)\s*-\s*([\d:APMapm]+)$/
  );
  if (!match) return [];
  const dayTokens = match[1].match(/Th|Tu|We|Fr|Sa|Su|Mo|M|T|W|R|F|S|U/gi) || [];
  const dayMap = {
    Mo:"Monday", Tu:"Tuesday", We:"Wednesday", Th:"Thursday",
    Fr:"Friday", Sa:"Saturday", Su:"Sunday",
    M:"Monday",  T:"Tuesday",  W:"Wednesday", R:"Thursday",
    F:"Friday",  S:"Saturday", U:"Sunday",
  };
  return dayTokens
    .map(t => dayMap[t.charAt(0).toUpperCase() + t.slice(1).toLowerCase()] || dayMap[t.toUpperCase()] || dayMap[t])
    .filter(Boolean)
    .map(day => ({ day, startTime: match[2], endTime: match[3] }));
}

function timeToMinutes(timeText) {
  if (!timeText) return Infinity;
  const match = timeText.trim().match(/^(\d{1,2})(?::(\d{2}))?(AM|PM)$/i);
  if (!match) return Infinity;
  let h = parseInt(match[1], 10);
  const m = parseInt(match[2] || "0", 10);
  const period = match[3].toUpperCase();
  if (h === 12) h = 0;
  if (period === "PM") h += 12;
  return h * 60 + m;
}

function renderSchedule(courses = []) {
  const container   = document.getElementById("schedule-container");
  const placeholder = document.getElementById("schedule-placeholder");
  const grid        = document.getElementById("schedule-grid");
  const coursesWithSchedule = courses.filter(c => c.days_times && c.days_times.trim());

  if (!coursesWithSchedule.length) {
    container.style.display = "none";
    placeholder.style.display = "block";
    return;
  }

  container.style.display = "block";
  placeholder.style.display = "none";
  grid.innerHTML = "";

  const coursesByDay = {};
  coursesWithSchedule.forEach(course => {
    parseDaysTimes(course.days_times).forEach(({ day, startTime, endTime }) => {
      if (!coursesByDay[day]) coursesByDay[day] = [];
      coursesByDay[day].push({
        code: course.course_code, title: course.title,
        time: `${startTime} - ${endTime}`,
        instructor: course.instructor || "TBA",
      });
    });
  });

  ["Monday","Tuesday","Wednesday","Thursday","Friday"].forEach(day => {
    const dayDiv = document.createElement("div");
    dayDiv.className = "schedule-day";
    const hdr = document.createElement("h4");
    hdr.textContent = day;
    dayDiv.appendChild(hdr);

    if (coursesByDay[day]) {
      coursesByDay[day]
        .sort((a, b) => timeToMinutes(a.time.split(" - ")[0]) - timeToMinutes(b.time.split(" - ")[0]))
        .forEach(course => {
          const div = document.createElement("div");
          div.className = "schedule-course";
          const strong = document.createElement("strong");
          strong.textContent = course.code;
          const time = document.createElement("p");
          time.className = "schedule-time";
          time.textContent = `${course.time} . ${course.instructor}`;
          div.append(strong, time);
          dayDiv.appendChild(div);
        });
    } else {
      const empty = document.createElement("p");
      empty.className = "schedule-empty";
      empty.textContent = "No classes";
      dayDiv.appendChild(empty);
    }
    grid.appendChild(dayDiv);
  });
}

function renderProgress(advisor) {
  if (!advisor) { progressContainer.style.display = "none"; return; }
  const sel = advisor.total_units_selected  || 0;
  const req = advisor.total_units_required  || 0;
  progressContainer.style.display = "block";
  if (req > 0) {
    progressText.textContent = `${sel} / ${req} units toward degree`;
    progressFill.style.width  = `${Math.min(100, (sel / req) * 100)}%`;
  } else {
    progressText.textContent = `${sel} units selected`;
    progressFill.style.width  = "0%";
  }
}

async function handleAdvisorPayload(advisor) {
  if (!advisor) return;
  await renderRecommendations(advisor.grouped_recommendations || [], advisor.recommendations || []);
  renderSchedule(advisor.recommendations || []);
  renderProgress(advisor);
  renderPrereqBlocked(advisor.prerequisite_blocked_courses || []);
  explanationEl.textContent = advisor.explanation || "No explanation provided.";
  updateSidebar(advisor);
}

function buildOutgoingState() {
  const blocked = blockedWindows.map(w => ({
    day: w.day,
    start: formatTime24To12(w.start),
    end:   formatTime24To12(w.end),
  }));
  const maxUnits = parseInt(chatMaxUnitsInput.value, 10);
  return {
    ...conversationState,
    max_units_per_semester:
      Number.isFinite(maxUnits) && maxUnits > 0
        ? maxUnits : conversationState.max_units_per_semester,
    blocked_time_windows: blocked,
  };
}

function applyResponseState(state) {
  if (!state) return;
  conversationState = {
    major:                     state.major               ?? conversationState.major,
    term:                      state.term                ?? conversationState.term,
    completed_courses:         Array.isArray(state.completed_courses)
                                 ? state.completed_courses : conversationState.completed_courses,
    preferences_text:          state.preferences_text    ?? conversationState.preferences_text,
    prefer_high_rated_professors: !!state.prefer_high_rated_professors,
    prefer_light_workload:        !!state.prefer_light_workload,
    max_units_per_semester:    state.max_units_per_semester ?? conversationState.max_units_per_semester,
    blocked_time_windows:      Array.isArray(state.blocked_time_windows)
                                 ? state.blocked_time_windows : conversationState.blocked_time_windows,
  };
  renderChatStateDebug();
}

chatForm.addEventListener("submit", async event => {
  event.preventDefault();
  const message = chatInput.value.trim();
  if (!message) return;

  appendMessage("user", message, "You");
  conversationHistory.push({ role: "user", content: message });
  chatInput.value = "";
  sendButton.disabled = true;
  appendThinkingIndicator();
  setChatStatus("Sending to advisor...", "info");

  try {
    const payload = {
      message,
      state:   buildOutgoingState(),
      history: conversationHistory.slice(-8),
    };
    const _send = (typeof sendChatMessage === "function")
      ? sendChatMessage
      : async (p) => {
          const r = await fetch(`${API_BASE_URL}/advisor/chat`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(p),
          });
          if (!r.ok) {
            let d = "";
            try { const b = await r.json(); d = b?.detail ? `: ${b.detail}` : ""; } catch {}
            throw new Error(`Chat request failed (${r.status})${d}`);
          }
          return r.json();
        };
    const data = await _send(payload);
    removeThinkingIndicator();

    appendMessage("assistant", data.reply || "(no reply)", "SF State Advisor");
    conversationHistory.push({ role: "assistant", content: data.reply || "" });

    applyResponseState(data.state);
    await handleAdvisorPayload(data.advisor);

    const sourceLabel = data.intent_source === "llm" ? "intent: LLM"
      : data.intent_source === "regex" ? "intent: regex (fast path)"
      : "intent: regex fallback";
    const rationaleLabel = data.rationale_source === "llm" ? " . rationales: LLM"
      : data.rationale_source === "template" ? " . rationales: template"
      : data.rationale_source === "llm+template" ? " . rationales: LLM + template"
      : "";
    setChatStatus(`Done (${sourceLabel}${rationaleLabel}).`, "success");

    if (data.missing_required_fields && data.missing_required_fields.length) {
      setChatStatus(`Need ${data.missing_required_fields.join(", ")} to recommend courses.`, "info");
    }

    if (data.advisor && data.advisor.recommendations && data.advisor.recommendations.length) {
      document.querySelector(".nav-btn[data-tab='results']").click();
    }
  } catch (error) {
    removeThinkingIndicator();
    appendMessage("assistant", `Sorry, I hit an error: ${error.message}`, "SF State Advisor");
    setChatStatus(`Error: ${error.message}`, "error");
  } finally {
    sendButton.disabled = false;
    chatInput.focus();
  }
});

renderChatStateDebug();
updateSidebar(null);