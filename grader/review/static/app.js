(() => {
  const state = {
    runInfo: null,
    submissions: [],
    currentSubmission: null,
    currentQuestionId: null,
    currentDocIdx: 0,
    currentPageIdx: 0,
    scale: 1.2,
    currentTab: "review",
    pendingPatch: {},
    pendingPatchTimer: null,
    pendingNoteTimer: null,
    dragActive: false,
  };

  const ui = {
    tabReviewBtn: document.getElementById("tabReviewBtn"),
    tabConfigBtn: document.getElementById("tabConfigBtn"),
    reviewPanel: document.getElementById("reviewPanel"),
    configPanel: document.getElementById("configPanel"),
    queueList: document.getElementById("queueList"),
    searchInput: document.getElementById("searchInput"),
    refreshBtn: document.getElementById("refreshBtn"),
    exportBtn: document.getElementById("exportBtn"),
    docSelect: document.getElementById("docSelect"),
    pageInput: document.getElementById("pageInput"),
    scaleInput: document.getElementById("scaleInput"),
    loadPageBtn: document.getElementById("loadPageBtn"),
    imageWrap: document.getElementById("imageWrap"),
    pageImage: document.getElementById("pageImage"),
    marker: document.getElementById("marker"),
    viewerMeta: document.getElementById("viewerMeta"),
    submissionTitle: document.getElementById("submissionTitle"),
    summaryBox: document.getElementById("summaryBox"),
    questionSelect: document.getElementById("questionSelect"),
    verdictSelect: document.getElementById("verdictSelect"),
    confidenceInput: document.getElementById("confidenceInput"),
    sourceFileSelect: document.getElementById("sourceFileSelect"),
    pageNumberInput: document.getElementById("pageNumberInput"),
    reasonInput: document.getElementById("reasonInput"),
    evidenceInput: document.getElementById("evidenceInput"),
    noteInput: document.getElementById("noteInput"),
    solutionsPathInput: document.getElementById("solutionsPathInput"),
    rubricPathInput: document.getElementById("rubricPathInput"),
    gpCheckPlus: document.getElementById("gpCheckPlus"),
    gpCheck: document.getElementById("gpCheck"),
    gpCheckMinus: document.getElementById("gpCheckMinus"),
    gpReviewRequired: document.getElementById("gpReviewRequired"),
    bandCheckPlusMin: document.getElementById("bandCheckPlusMin"),
    bandCheckMin: document.getElementById("bandCheckMin"),
    partialCreditInput: document.getElementById("partialCreditInput"),
    questionRulesList: document.getElementById("questionRulesList"),
    reloadConfigBtn: document.getElementById("reloadConfigBtn"),
    saveConfigBtn: document.getElementById("saveConfigBtn"),
    configStatus: document.getElementById("configStatus"),
  };

  async function apiGet(path) {
    const res = await fetch(path);
    const payload = await res.json();
    if (!res.ok) {
      throw new Error(payload.error || `GET ${path} failed`);
    }
    return payload;
  }

  async function apiPatch(path, body) {
    const res = await fetch(path, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const payload = await res.json();
    if (!res.ok) {
      throw new Error(payload.error || `PATCH ${path} failed`);
    }
    return payload;
  }

  async function apiPost(path, body) {
    const res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    const payload = await res.json();
    if (!res.ok) {
      throw new Error(payload.error || `POST ${path} failed`);
    }
    return payload;
  }

  function setStatus(message) {
    ui.viewerMeta.textContent = message;
  }

  function setConfigStatus(message) {
    ui.configStatus.textContent = message;
  }

  function setTab(tab) {
    state.currentTab = tab;
    const reviewActive = tab === "review";
    ui.tabReviewBtn.classList.toggle("active", reviewActive);
    ui.tabConfigBtn.classList.toggle("active", !reviewActive);
    ui.reviewPanel.classList.toggle("hidden", !reviewActive);
    ui.configPanel.classList.toggle("hidden", reviewActive);
  }

  async function refreshRun() {
    state.runInfo = await apiGet("/api/run");
    renderConfig();
  }

  async function refreshQueue() {
    const q = encodeURIComponent(ui.searchInput.value.trim());
    const payload = await apiGet(`/api/submissions?q=${q}`);
    state.submissions = payload.items || [];
    renderQueue();
  }

  function renderQueue() {
    ui.queueList.innerHTML = "";
    state.submissions.forEach((item) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className =
        "queue-item" +
        (state.currentSubmission && state.currentSubmission.submission_id === item.submission_id ? " active" : "");
      btn.textContent = `${item.student_name} | ${item.final_band} | needs_review:${item.needs_review_count}`;
      btn.addEventListener("click", () => selectSubmission(item.submission_id));
      ui.queueList.appendChild(btn);
    });
  }

  async function selectSubmission(submissionId) {
    await flushPatch();
    await flushNote();
    const payload = await apiGet(`/api/submissions/${submissionId}`);
    state.currentSubmission = payload;
    state.currentQuestionId = firstQuestionId(payload);
    state.currentDocIdx = 0;
    state.currentPageIdx = 0;
    ui.pageInput.value = "1";
    buildDocSelect();
    buildQuestionSelect();
    renderSubmission();
    await loadCurrentPage();
  }

  function firstQuestionId(submission) {
    const questions = submission.questions || {};
    return Object.keys(questions).sort()[0] || null;
  }

  function buildDocSelect() {
    ui.docSelect.innerHTML = "";
    const docs = state.currentSubmission?.documents || [];
    docs.forEach((doc) => {
      const option = document.createElement("option");
      option.value = String(doc.doc_idx);
      option.textContent = doc.filename + (doc.exists ? "" : " (missing)");
      ui.docSelect.appendChild(option);
    });
    ui.docSelect.value = String(state.currentDocIdx);
  }

  function buildQuestionSelect() {
    ui.questionSelect.innerHTML = "";
    const questions = state.currentSubmission?.questions || {};
    Object.keys(questions)
      .sort()
      .forEach((questionId) => {
        const option = document.createElement("option");
        option.value = questionId;
        option.textContent = questionId;
        ui.questionSelect.appendChild(option);
      });
    if (state.currentQuestionId) {
      ui.questionSelect.value = state.currentQuestionId;
    }
  }

  function renderSubmission() {
    const submission = state.currentSubmission;
    if (!submission) {
      return;
    }
    const identity = submission.identity || {};
    const summary = submission.final_summary || {};
    ui.submissionTitle.textContent = identity.student_name || "Submission";
    ui.summaryBox.textContent = `Band: ${summary.band || ""} | Percent: ${summary.percent || 0} | Points: ${summary.points || ""}`;

    const question = getCurrentQuestion();
    if (!question) {
      ui.marker.hidden = true;
      return;
    }

    const finalData = question.final || {};
    ui.verdictSelect.value = finalData.verdict || "needs_review";
    ui.confidenceInput.value = String(finalData.confidence ?? 0);
    ui.pageNumberInput.value = finalData.page_number || "";
    ui.reasonInput.value = finalData.short_reason || "";
    ui.evidenceInput.value = finalData.evidence_quote || "";
    ui.noteInput.value = submission.note || "";

    const docNames = (submission.documents || []).map((d) => d.filename);
    ui.sourceFileSelect.innerHTML = "";
    const emptyOption = document.createElement("option");
    emptyOption.value = "";
    emptyOption.textContent = "(none)";
    ui.sourceFileSelect.appendChild(emptyOption);
    docNames.forEach((name) => {
      const option = document.createElement("option");
      option.value = name;
      option.textContent = name;
      ui.sourceFileSelect.appendChild(option);
    });
    ui.sourceFileSelect.value = finalData.source_file || "";

    renderMarker();
  }

  function renderConfig() {
    const runInfo = state.runInfo;
    if (!runInfo) {
      return;
    }
    const gradingContext = runInfo.grading_context || {};
    const argsSnapshot = gradingContext.args_snapshot || {};
    const gradePoints = gradingContext.grade_points || {};
    const rubric = gradingContext.rubric || {};
    const bands = rubric.bands || {};

    ui.solutionsPathInput.value = argsSnapshot.solutions_pdf || "";
    ui.rubricPathInput.value = argsSnapshot.rubric_yaml || "";
    ui.gpCheckPlus.value = gradePoints["Check Plus"] || "";
    ui.gpCheck.value = gradePoints["Check"] || "";
    ui.gpCheckMinus.value = gradePoints["Check Minus"] || "";
    ui.gpReviewRequired.value = gradePoints["REVIEW_REQUIRED"] || "";
    ui.bandCheckPlusMin.value = String(bands.check_plus_min ?? 0.9);
    ui.bandCheckMin.value = String(bands.check_min ?? 0.7);
    ui.partialCreditInput.value = String(rubric.partial_credit ?? 0.5);

    ui.questionRulesList.innerHTML = "";
    const questions = Array.isArray(rubric.questions) ? rubric.questions : [];
    questions.forEach((question) => {
      const row = document.createElement("div");
      row.className = "question-rule-row";
      row.dataset.questionId = String(question.id || "");

      const id = document.createElement("strong");
      id.textContent = `Q${question.id || "?"}`;

      const labels = document.createElement("label");
      labels.textContent = "Label Patterns (comma separated)";
      const labelsInput = document.createElement("input");
      labelsInput.type = "text";
      labelsInput.className = "rule-label-patterns";
      labelsInput.value = (question.label_patterns || []).join(", ");
      labels.appendChild(labelsInput);

      const rules = document.createElement("label");
      rules.textContent = "Scoring Rules";
      const rulesInput = document.createElement("textarea");
      rulesInput.rows = 3;
      rulesInput.className = "rule-scoring";
      rulesInput.value = question.scoring_rules || "";
      rules.appendChild(rulesInput);

      row.appendChild(id);
      row.appendChild(labels);
      row.appendChild(rules);
      ui.questionRulesList.appendChild(row);
    });
  }

  function getCurrentQuestion() {
    const submission = state.currentSubmission;
    if (!submission || !state.currentQuestionId) {
      return null;
    }
    return submission.questions?.[state.currentQuestionId] || null;
  }

  function renderMarker() {
    const question = getCurrentQuestion();
    if (!question) {
      ui.marker.hidden = true;
      return;
    }
    const coords = question.final?.coords;
    if (!coords || coords.length !== 2) {
      ui.marker.hidden = true;
      return;
    }

    const imgRect = ui.pageImage.getBoundingClientRect();
    const wrapRect = ui.imageWrap.getBoundingClientRect();
    if (!imgRect.width || !imgRect.height) {
      ui.marker.hidden = true;
      return;
    }
    const y = Number(coords[0]);
    const x = Number(coords[1]);
    const px = (x / 1000) * imgRect.width;
    const py = (y / 1000) * imgRect.height;
    ui.marker.style.left = `${imgRect.left - wrapRect.left + px}px`;
    ui.marker.style.top = `${imgRect.top - wrapRect.top + py}px`;
    ui.marker.hidden = false;
  }

  async function loadCurrentPage() {
    const submission = state.currentSubmission;
    if (!submission) {
      return;
    }
    const scale = Number(ui.scaleInput.value || state.scale || 1.2);
    state.scale = Number.isFinite(scale) ? scale : 1.2;

    const page = Math.max(0, Number(ui.pageInput.value || "1") - 1);
    state.currentPageIdx = page;

    const meta = await apiGet(
      `/api/submissions/${submission.submission_id}/documents/${state.currentDocIdx}/pages/${state.currentPageIdx}/meta?scale=${state.scale}`
    );
    ui.pageImage.src = meta.image_url;
    setStatus(
      `Doc ${state.currentDocIdx + 1}, page ${state.currentPageIdx + 1} | ${meta.image_width_px}x${meta.image_height_px}px`
    );
  }

  function convertClientPointToNormalized(clientX, clientY) {
    const rect = ui.pageImage.getBoundingClientRect();
    if (!rect.width || !rect.height) {
      return null;
    }
    const x = clientX - rect.left;
    const y = clientY - rect.top;
    const xNorm = Math.max(0, Math.min(1000, (x / rect.width) * 1000));
    const yNorm = Math.max(0, Math.min(1000, (y / rect.height) * 1000));
    return [yNorm, xNorm];
  }

  function queuePatch(changes, delayMs) {
    state.pendingPatch = { ...state.pendingPatch, ...changes };
    if (state.pendingPatchTimer) {
      clearTimeout(state.pendingPatchTimer);
    }
    state.pendingPatchTimer = setTimeout(() => {
      flushPatch().catch((error) => alert(error.message));
    }, delayMs);
  }

  async function flushPatch() {
    if (!state.currentSubmission || !state.currentQuestionId) {
      return;
    }
    if (!Object.keys(state.pendingPatch).length) {
      return;
    }

    const payload = state.pendingPatch;
    state.pendingPatch = {};
    if (state.pendingPatchTimer) {
      clearTimeout(state.pendingPatchTimer);
      state.pendingPatchTimer = null;
    }

    const res = await apiPatch(
      `/api/submissions/${state.currentSubmission.submission_id}/questions/${state.currentQuestionId}`,
      payload
    );

    const submission = state.currentSubmission;
    submission.questions[state.currentQuestionId] = res.question;
    submission.final_summary = res.summary;
    renderSubmission();
    renderQueue();
  }

  function queueNoteSave(delayMs) {
    if (state.pendingNoteTimer) {
      clearTimeout(state.pendingNoteTimer);
    }
    state.pendingNoteTimer = setTimeout(() => {
      flushNote().catch((error) => alert(error.message));
    }, delayMs);
  }

  async function flushNote() {
    if (!state.currentSubmission) {
      return;
    }
    if (state.pendingNoteTimer) {
      clearTimeout(state.pendingNoteTimer);
      state.pendingNoteTimer = null;
    }
    await apiPatch(`/api/submissions/${state.currentSubmission.submission_id}/note`, {
      note: ui.noteInput.value || "",
    });
  }

  function collectConfigPayload() {
    const runInfo = state.runInfo;
    const gradingContext = runInfo?.grading_context || {};
    const baseRubric = structuredClone(gradingContext.rubric || {});
    const baseQuestions = Array.isArray(baseRubric.questions) ? baseRubric.questions : [];

    baseRubric.bands = {
      check_plus_min: Number(ui.bandCheckPlusMin.value || "0.9"),
      check_min: Number(ui.bandCheckMin.value || "0.7"),
    };
    baseRubric.partial_credit = Number(ui.partialCreditInput.value || "0.5");

    const rowMap = new Map();
    ui.questionRulesList.querySelectorAll(".question-rule-row").forEach((row) => {
      const questionId = row.dataset.questionId;
      if (!questionId) {
        return;
      }
      const labelsRaw = row.querySelector(".rule-label-patterns")?.value || "";
      const scoringRaw = row.querySelector(".rule-scoring")?.value || "";
      rowMap.set(questionId, {
        label_patterns: labelsRaw
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
        scoring_rules: scoringRaw,
      });
    });

    baseRubric.questions = baseQuestions.map((question) => {
      const override = rowMap.get(String(question.id || ""));
      if (!override) {
        return question;
      }
      return {
        ...question,
        label_patterns: override.label_patterns,
        scoring_rules: override.scoring_rules,
      };
    });

    return {
      grade_points: {
        "Check Plus": ui.gpCheckPlus.value,
        "Check": ui.gpCheck.value,
        "Check Minus": ui.gpCheckMinus.value,
        "REVIEW_REQUIRED": ui.gpReviewRequired.value,
      },
      rubric: baseRubric,
    };
  }

  async function saveConfig() {
    await flushPatch();
    await flushNote();
    const payload = collectConfigPayload();
    const response = await apiPatch("/api/grading-context", payload);
    state.runInfo.grading_context = response.grading_context;
    renderConfig();
    await refreshQueue();
    if (state.currentSubmission) {
      await selectSubmission(state.currentSubmission.submission_id);
    }
    setConfigStatus(`Saved config. Recomputed ${response.recomputed_submissions} submissions.`);
  }

  function bindEvents() {
    ui.tabReviewBtn.addEventListener("click", () => setTab("review"));
    ui.tabConfigBtn.addEventListener("click", () => setTab("config"));

    ui.refreshBtn.addEventListener("click", () => {
      refreshQueue().catch((error) => alert(error.message));
    });

    ui.searchInput.addEventListener("input", () => {
      refreshQueue().catch((error) => alert(error.message));
    });

    ui.exportBtn.addEventListener("click", async () => {
      await flushPatch();
      await flushNote();
      const result = await apiPost("/api/export", {});
      alert(`Export complete. Artifacts: ${Object.keys(result.artifacts || {}).length}`);
    });

    ui.reloadConfigBtn.addEventListener("click", async () => {
      await refreshRun();
      setConfigStatus("Reloaded config from state.");
    });

    ui.saveConfigBtn.addEventListener("click", () => {
      saveConfig().catch((error) => {
        setConfigStatus(`Save failed: ${error.message}`);
        alert(error.message);
      });
    });

    ui.docSelect.addEventListener("change", async () => {
      state.currentDocIdx = Number(ui.docSelect.value || "0");
      state.currentPageIdx = 0;
      ui.pageInput.value = "1";
      await loadCurrentPage();
      renderMarker();
    });

    ui.loadPageBtn.addEventListener("click", () => {
      loadCurrentPage().then(renderMarker).catch((error) => alert(error.message));
    });

    ui.pageImage.addEventListener("load", () => {
      renderMarker();
    });

    window.addEventListener("resize", () => {
      renderMarker();
    });

    ui.questionSelect.addEventListener("change", async () => {
      await flushPatch();
      state.currentQuestionId = ui.questionSelect.value;
      renderSubmission();
    });

    ui.verdictSelect.addEventListener("change", () => queuePatch({ verdict_final: ui.verdictSelect.value }, 150));
    ui.confidenceInput.addEventListener("input", () =>
      queuePatch({ confidence_final: Number(ui.confidenceInput.value || "0") }, 550)
    );
    ui.reasonInput.addEventListener("input", () => queuePatch({ short_reason_final: ui.reasonInput.value || "" }, 550));
    ui.evidenceInput.addEventListener("input", () =>
      queuePatch({ evidence_quote_final: ui.evidenceInput.value || "" }, 550)
    );
    ui.sourceFileSelect.addEventListener("change", () =>
      queuePatch({ source_file_final: ui.sourceFileSelect.value || null }, 150)
    );
    ui.pageNumberInput.addEventListener("input", () => {
      const raw = ui.pageNumberInput.value.trim();
      queuePatch({ page_final: raw ? Number(raw) : null }, 550);
    });

    ui.noteInput.addEventListener("input", () => queueNoteSave(600));
    ui.noteInput.addEventListener("blur", () => {
      flushNote().catch((error) => alert(error.message));
    });

    ui.imageWrap.addEventListener("click", (event) => {
      if (state.dragActive) {
        return;
      }
      const coords = convertClientPointToNormalized(event.clientX, event.clientY);
      if (!coords) {
        return;
      }
      queuePatch({ coords_final: coords }, 250);
      const question = getCurrentQuestion();
      if (question) {
        question.final.coords = coords;
      }
      renderMarker();
    });

    ui.marker.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      state.dragActive = true;
      ui.marker.classList.add("dragging");
      ui.marker.setPointerCapture(event.pointerId);
    });

    ui.marker.addEventListener("pointermove", (event) => {
      if (!state.dragActive) {
        return;
      }
      const coords = convertClientPointToNormalized(event.clientX, event.clientY);
      if (!coords) {
        return;
      }
      queuePatch({ coords_final: coords }, 300);
      const question = getCurrentQuestion();
      if (question) {
        question.final.coords = coords;
      }
      renderMarker();
    });

    ui.marker.addEventListener("pointerup", async (event) => {
      event.preventDefault();
      state.dragActive = false;
      ui.marker.classList.remove("dragging");
      await flushPatch();
    });
  }

  async function init() {
    bindEvents();
    setTab("review");
    await refreshRun();
    await refreshQueue();
    if (state.submissions.length > 0) {
      await selectSubmission(state.submissions[0].submission_id);
      renderQueue();
    }
  }

  init().catch((error) => {
    setStatus(`Failed to initialize UI: ${error.message}`);
    alert(error.message);
  });
})();
