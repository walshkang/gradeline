(() => {
  const state = {
    runInfo: null,
    submissions: [],
    currentSubmission: null,
    documentSource: "original",
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
    runOutcomeSummary: document.getElementById("runOutcomeSummary"),
    docSourceSelect: document.getElementById("docSourceSelect"),
    docSelect: document.getElementById("docSelect"),
    pageInput: document.getElementById("pageInput"),
    prevPageBtn: document.getElementById("prevPageBtn"),
    nextPageBtn: document.getElementById("nextPageBtn"),
    scaleInput: document.getElementById("scaleInput"),
    loadPageBtn: document.getElementById("loadPageBtn"),
    imageWrap: document.getElementById("imageWrap"),
    pageImage: document.getElementById("pageImage"),
    emptyViewer: document.getElementById("emptyViewer"),
    marker: document.getElementById("marker"),
    viewerMeta: document.getElementById("viewerMeta"),
    submissionTitle: document.getElementById("submissionTitle"),
    summaryBox: document.getElementById("summaryBox"),
    questionSelect: document.getElementById("questionSelect"),
    verdictSelect: document.getElementById("verdictSelect"),
    confidenceInput: document.getElementById("confidenceInput"),
    sourceFileSelect: document.getElementById("sourceFileSelect"),
    pageNumberInput: document.getElementById("pageNumberInput"),
    logicAnalysisInput: document.getElementById("logicAnalysisInput"),
    reasonInput: document.getElementById("reasonInput"),
    detailReasonInput: document.getElementById("detailReasonInput"),
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
    toastContainer: document.getElementById("toastContainer"),
    debugOverlayToggle: document.getElementById("debugOverlayToggle"),
    debugOverlayPanel: document.getElementById("debugOverlayPanel"),
  };

  // --- Toast notifications ---

  function showToast(message, type = "default") {
    const toast = document.createElement("div");
    toast.className = `toast${type !== "default" ? ` toast-${type}` : ""}`;
    toast.textContent = message;
    ui.toastContainer.appendChild(toast);
    setTimeout(() => {
      if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, 3200);
  }

  // --- API helpers ---

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

  // --- Badge helper ---

  function bandBadgeClass(band) {
    if (!band) return "badge";
    const b = band.toUpperCase();
    if (b === "CHECK_PLUS" || b === "CHECK PLUS") return "badge badge-check-plus";
    if (b === "CHECK") return "badge badge-check";
    if (b === "CHECK_MINUS" || b === "CHECK MINUS") return "badge badge-check-minus";
    if (b === "REVIEW_REQUIRED") return "badge badge-review";
    return "badge";
  }

  function bandLabel(band) {
    if (!band) return "—";
    return band.replace(/_/g, " ");
  }

  // --- Data fetching ---

  async function refreshRun() {
    state.runInfo = await apiGet("/api/run");
    state.documentSource = ui.docSourceSelect.value || "original";
    renderRunOutcomes();
    renderConfig();
  }

  function renderRunOutcomes() {
    const outcomes = state.runInfo?.outcomes;
    if (!outcomes || !outcomes.available) {
      ui.runOutcomeSummary.textContent = "No run summary available yet.";
      return;
    }

    const lines = [
      `Processed: ${Number(outcomes.submissions_processed || 0)}`,
      `Success: ${Number(outcomes.success_count || 0)}`,
      `Review Required: ${Number(outcomes.review_required_count || 0)}`,
      `Failed: ${Number(outcomes.failed_with_error_count || 0)}`,
    ];

    const warningCount = Number(outcomes.warning_count || 0);
    const cacheWarnings = Number(outcomes.cache_warning_count || 0);
    lines.push(`Warnings: ${warningCount}${cacheWarnings ? ` (${cacheWarnings} cache)` : ""}`);

    const bandCounts = outcomes.band_counts || {};
    const bandEntries = Object.entries(bandCounts).filter(([, value]) => Number(value) > 0);
    if (bandEntries.length > 0) {
      lines.push("");
      lines.push("Bands:");
      bandEntries
        .sort((a, b) => String(a[0]).localeCompare(String(b[0])))
        .forEach(([band, count]) => lines.push(`  ${band}: ${count}`));
    }

    const errorSubmissions = Array.isArray(outcomes.error_submissions) ? outcomes.error_submissions : [];
    if (errorSubmissions.length > 0) {
      lines.push("");
      lines.push("Failures:");
      errorSubmissions.slice(0, 3).forEach((item) => {
        const name = item.student_name || item.folder || "Unknown";
        lines.push(`  ${name}`);
      });
    }

    const unmatched = Number(outcomes.unmatched_grade_rows || 0);
    if (unmatched > 0) {
      lines.push("");
      lines.push(`Unmatched rows: ${unmatched}`);
    }

    ui.runOutcomeSummary.textContent = lines.join("\n");
  }

  function sourceQueryParam() {
    return encodeURIComponent(state.documentSource || "original");
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

      const nameSpan = document.createElement("span");
      nameSpan.className = "student-name";
      nameSpan.textContent = item.student_name;

      const metaDiv = document.createElement("div");
      metaDiv.className = "queue-meta";

      const bandSpan = document.createElement("span");
      bandSpan.className = bandBadgeClass(item.final_band);
      bandSpan.textContent = bandLabel(item.final_band);
      metaDiv.appendChild(bandSpan);

      if (item.needs_review_count > 0) {
        const reviewBadge = document.createElement("span");
        reviewBadge.className = "badge badge-count";
        reviewBadge.textContent = `${item.needs_review_count} review`;
        metaDiv.appendChild(reviewBadge);
      }

      btn.appendChild(nameSpan);
      btn.appendChild(metaDiv);
      btn.addEventListener("click", () => selectSubmission(item.submission_id));
      ui.queueList.appendChild(btn);
    });

    scrollToActiveItem();
  }

  function scrollToActiveItem() {
    const active = ui.queueList.querySelector(".queue-item.active");
    if (active) {
      active.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }

  // --- Submission selection ---

  async function selectSubmission(submissionId) {
    await flushPatch();
    await flushNote();
    const payload = await apiGet(`/api/submissions/${submissionId}?doc_source=${sourceQueryParam()}`);
    state.currentSubmission = payload;
    renderQueue();
    state.currentQuestionId = firstQuestionId(payload);
    const docs = Array.isArray(payload.documents) ? payload.documents : [];
    const firstExistingDocIdx = docs.findIndex((doc) => doc.exists);
    state.currentDocIdx = firstExistingDocIdx >= 0 ? firstExistingDocIdx : 0;
    state.currentPageIdx = 0;
    ui.pageInput.value = "1";
    buildDocSelect();
    buildQuestionSelect();
    renderSubmission();

    // Show/hide empty state
    if (docs.length === 0) {
      showEmptyViewer("No PDF documents available.");
      return;
    }
    if (firstExistingDocIdx < 0) {
      showEmptyViewer(`No ${state.documentSource} PDFs found. Switch source or run export first.`);
      return;
    }
    hideEmptyViewer();
    await loadCurrentPage();
  }

  function showEmptyViewer(message) {
    ui.pageImage.style.display = "none";
    ui.pageImage.removeAttribute("src");
    ui.marker.hidden = true;
    if (ui.emptyViewer) {
      ui.emptyViewer.classList.remove("hidden");
      ui.emptyViewer.querySelector(".empty-state-text").textContent = message;
    }
    setStatus(message);
  }

  function hideEmptyViewer() {
    ui.pageImage.style.display = "block";
    if (ui.emptyViewer) {
      ui.emptyViewer.classList.add("hidden");
    }
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
    ui.summaryBox.textContent = `Band: ${summary.band || "—"} · Percent: ${summary.percent || 0}% · Points: ${summary.points || "—"}`;

    const question = getCurrentQuestion();
    if (!question) {
      ui.marker.hidden = true;
      updateDebugOverlay(null);
      return;
    }

    const finalData = question.final || {};
    ui.verdictSelect.value = finalData.verdict || "needs_review";
    ui.confidenceInput.value = String(finalData.confidence ?? 0);
    ui.pageNumberInput.value = finalData.page_number || "";
    ui.logicAnalysisInput.value = finalData.logic_analysis || "";
    ui.reasonInput.value = finalData.short_reason || "";
    ui.detailReasonInput.value = finalData.detail_reason || "";
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
    updateDebugOverlay(finalData);
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
      labels.textContent = "Label Patterns";
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

  function isDebugOverlayEnabled() {
    return !!ui.debugOverlayToggle && ui.debugOverlayToggle.checked;
  }

  function updateDebugOverlay(finalData) {
    if (!ui.debugOverlayPanel) {
      return;
    }
    if (!isDebugOverlayEnabled() || !finalData) {
      ui.debugOverlayPanel.textContent = "";
      ui.debugOverlayPanel.classList.add("hidden");
      return;
    }
    const placementSource = finalData.placement_source || "unknown";
    const coords = Array.isArray(finalData.coords) ? finalData.coords : null;
    const page = finalData.page_number || "";
    const sourceFile = finalData.source_file || "";
    const lines = [];
    lines.push(`placement_source: ${placementSource}`);
    if (coords && coords.length === 2) {
      lines.push(`coords (y,x): [${coords[0].toFixed ? coords[0].toFixed(1) : coords[0]}, ${coords[1].toFixed ? coords[1].toFixed(1) : coords[1]}]`);
    } else {
      lines.push("coords: <none>");
    }
    lines.push(`page_number: ${page || "?"}`);
    lines.push(`source_file: ${sourceFile || "(none)"}`);
    ui.debugOverlayPanel.textContent = lines.join("\n");
    ui.debugOverlayPanel.classList.remove("hidden");
  }

  async function loadCurrentPage() {
    const submission = state.currentSubmission;
    if (!submission) {
      return;
    }
    const docs = Array.isArray(submission.documents) ? submission.documents : [];
    const currentDoc = docs[state.currentDocIdx];
    if (!currentDoc) {
      showEmptyViewer("Selected document is unavailable.");
      return;
    }
    if (!currentDoc.exists) {
      showEmptyViewer(`Missing file: ${currentDoc.filename}`);
      return;
    }
    const scale = Number(ui.scaleInput.value || state.scale || 1.2);
    state.scale = Number.isFinite(scale) ? scale : 1.2;

    const page = Math.max(0, Number(ui.pageInput.value || "1") - 1);
    state.currentPageIdx = page;

    const meta = await apiGet(
      `/api/submissions/${submission.submission_id}/documents/${state.currentDocIdx}/pages/${state.currentPageIdx}/meta?scale=${state.scale}&doc_source=${sourceQueryParam()}`
    );
    hideEmptyViewer();
    ui.pageImage.src = meta.image_url;
    setStatus(
      `${state.documentSource} · Doc ${state.currentDocIdx + 1}, page ${state.currentPageIdx + 1} · ${meta.image_width_px}×${meta.image_height_px}px`
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
      flushPatch().catch((error) => showToast(error.message, "error"));
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
      flushNote().catch((error) => showToast(error.message, "error"));
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
    showToast(`Config saved. Recomputed ${response.recomputed_submissions} submissions.`, "success");
    setConfigStatus(`Saved. Recomputed ${response.recomputed_submissions} submissions.`);
  }

  // --- Navigation helpers ---

  function navigateSubmission(delta) {
    if (!state.submissions.length) return;
    const currentIdx = state.submissions.findIndex(
      (s) => state.currentSubmission && s.submission_id === state.currentSubmission.submission_id
    );
    const nextIdx = Math.max(0, Math.min(state.submissions.length - 1, currentIdx + delta));
    if (nextIdx !== currentIdx) {
      selectSubmission(state.submissions[nextIdx].submission_id).catch((e) =>
        showToast(e.message, "error")
      );
    }
  }

  function navigatePage(delta) {
    const current = Number(ui.pageInput.value || "1");
    const next = Math.max(1, current + delta);
    ui.pageInput.value = String(next);
    loadCurrentPage().then(renderMarker).catch((e) => showToast(e.message, "error"));
  }

  // --- Event binding ---

  function bindEvents() {
    ui.tabReviewBtn.addEventListener("click", () => setTab("review"));
    ui.tabConfigBtn.addEventListener("click", () => setTab("config"));

    ui.refreshBtn.addEventListener("click", () => {
      refreshQueue().catch((error) => showToast(error.message, "error"));
    });

    ui.searchInput.addEventListener("input", () => {
      refreshQueue().catch((error) => showToast(error.message, "error"));
    });

    ui.docSourceSelect.addEventListener("change", async () => {
      state.documentSource = ui.docSourceSelect.value || "original";
      if (!state.currentSubmission) {
        return;
      }
      await selectSubmission(state.currentSubmission.submission_id);
    });

    ui.exportBtn.addEventListener("click", async () => {
      await flushPatch();
      await flushNote();
      try {
        const result = await apiPost("/api/export", {});
        const artifacts = result.artifacts || {};
        const count = Object.keys(artifacts).length;
        const reviewedFolder = artifacts["Reviewed PDFs folder"];
        showToast(`Export complete — ${count} artifacts written.`, "success");
        if (reviewedFolder) {
          setStatus(`Reviewed PDFs: ${reviewedFolder}`);
        }
      } catch (e) {
        showToast(`Export failed: ${e.message}`, "error");
      }
    });

    ui.reloadConfigBtn.addEventListener("click", async () => {
      await refreshRun();
      showToast("Config reloaded.", "success");
      setConfigStatus("Reloaded from state.");
    });

    ui.saveConfigBtn.addEventListener("click", () => {
      saveConfig().catch((error) => {
        setConfigStatus(`Save failed: ${error.message}`);
        showToast(error.message, "error");
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
      loadCurrentPage().then(renderMarker).catch((error) => showToast(error.message, "error"));
    });

    // Prev/next page buttons
    ui.prevPageBtn.addEventListener("click", () => navigatePage(-1));
    ui.nextPageBtn.addEventListener("click", () => navigatePage(1));

    ui.pageImage.addEventListener("load", () => {
      renderMarker();
      const question = getCurrentQuestion();
      updateDebugOverlay(question?.final || null);
    });

    window.addEventListener("resize", () => {
      renderMarker();
      const question = getCurrentQuestion();
      updateDebugOverlay(question?.final || null);
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
    ui.logicAnalysisInput.addEventListener("input", () => queuePatch({ logic_analysis_final: ui.logicAnalysisInput.value || "" }, 550));
    ui.reasonInput.addEventListener("input", () => queuePatch({ short_reason_final: ui.reasonInput.value || "" }, 550));
    ui.detailReasonInput.addEventListener("input", () =>
      queuePatch({ detail_reason_final: ui.detailReasonInput.value || "" }, 550)
    );
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
      flushNote().catch((error) => showToast(error.message, "error"));
    });

    if (ui.debugOverlayToggle) {
      ui.debugOverlayToggle.addEventListener("change", () => {
        const question = getCurrentQuestion();
        updateDebugOverlay(question?.final || null);
      });
    }

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

    // Keyboard shortcuts
    document.addEventListener("keydown", (event) => {
      // Skip if user is typing in an input/textarea
      const tag = document.activeElement?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;

      if (event.key === "j" || event.key === "ArrowDown") {
        event.preventDefault();
        navigateSubmission(1);
      } else if (event.key === "k" || event.key === "ArrowUp") {
        event.preventDefault();
        navigateSubmission(-1);
      } else if (event.key === "[") {
        event.preventDefault();
        navigatePage(-1);
      } else if (event.key === "]") {
        event.preventDefault();
        navigatePage(1);
      }
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
    setStatus(`Failed to initialize: ${error.message}`);
    showToast(error.message, "error");
  });
})();
