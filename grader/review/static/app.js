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
    matrixData: null,
    activeCoords: null,
    scrollPending: false,
  };

  const ui = {
    tabReviewBtn: document.getElementById("tabReviewBtn"),
    tabConfigBtn: document.getElementById("tabConfigBtn"),
    tabMatrixBtn: document.getElementById("tabMatrixBtn"),
    tabSetupBtn: document.getElementById("tabSetupBtn"),
    reviewPanel: document.getElementById("reviewPanel"),
    configPanel: document.getElementById("configPanel"),
    matrixPanel: document.getElementById("matrixPanel"),
    setupPanel: document.getElementById("setupPanel"),
    queueList: document.getElementById("queueList"),
    searchInput: document.getElementById("searchInput"),
    refreshBtn: document.getElementById("refreshBtn"),
    exportBtn: document.getElementById("exportBtn"),
    exportDropdown: document.getElementById("exportDropdown"),
    exportMenu: document.getElementById("exportMenu"),
    exportCsvBtn: document.getElementById("exportCsvBtn"),
    exportAuditBtn: document.getElementById("exportAuditBtn"),
    exportPdfsBtn: document.getElementById("exportPdfsBtn"),
    exportBundleBtn: document.getElementById("exportBundleBtn"),
    exportServerBtn: document.getElementById("exportServerBtn"),
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
    summaryText: document.getElementById("summaryText"),
    questionNavGrid: document.getElementById("questionNavGrid"),
    questionReviewedCheckbox: document.getElementById("questionReviewedCheckbox"),
    submissionStatusSelect: document.getElementById("submissionStatusSelect"),
    questionSelect: document.getElementById("questionSelect"),
    judgeCritiqueContainer: document.getElementById("judgeCritiqueContainer"),
    judgeCritiqueText: document.getElementById("judgeCritiqueText"),
    acceptJudgeFixBtn: document.getElementById("acceptJudgeFixBtn"),
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
    matrixSortSelect: document.getElementById("matrixSortSelect"),
    matrixFilterToggle: document.getElementById("matrixFilterToggle"),
    matrixGrid: document.getElementById("matrixGrid"),
    matrixDetail: document.getElementById("matrixDetail"),
    subpartsContainer: document.getElementById("subpartsContainer"),
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
    const configActive = tab === "config";
    const matrixActive = tab === "matrix";
    const setupActive = tab === "setup";
    
    ui.tabReviewBtn.classList.toggle("active", reviewActive);
    ui.tabConfigBtn.classList.toggle("active", configActive);
    if (ui.tabMatrixBtn) ui.tabMatrixBtn.classList.toggle("active", matrixActive);
    if (ui.tabSetupBtn) ui.tabSetupBtn.classList.toggle("active", setupActive);
    
    ui.reviewPanel.classList.toggle("hidden", !reviewActive);
    ui.configPanel.classList.toggle("hidden", !configActive);
    if (ui.matrixPanel) ui.matrixPanel.classList.toggle("hidden", !matrixActive);
    if (ui.setupPanel) ui.setupPanel.classList.toggle("hidden", !setupActive);
    
    if (matrixActive) {
      loadMatrix().catch(e => showToast(e.message, "error"));
    }
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

    const cost = outcomes.cost_summary;
    if (cost && (cost.total_cost_usd > 0 || cost.total_input_tokens > 0)) {
      lines.push("");
      lines.push("💰 LLM API Cost & Tokens:");
      lines.push(`  Total Cost: $${Number(cost.total_cost_usd || 0).toFixed(4)}`);
      lines.push(`  Avg / Student: $${Number(cost.avg_cost_per_student || 0).toFixed(4)}`);
      lines.push(`  Input Tokens: ${Number(cost.total_input_tokens || 0).toLocaleString()}`);
      lines.push(`  Output Tokens: ${Number(cost.total_output_tokens || 0).toLocaleString()}`);
      if (cost.total_cached_tokens) {
        lines.push(`  Cached Tokens: ${Number(cost.total_cached_tokens || 0).toLocaleString()}`);
      }
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

      if (item.review_status) {
        const statusSpan = document.createElement("span");
        statusSpan.className = `badge badge-${item.review_status}`;
        statusSpan.textContent =
          item.review_status === "in_progress"
            ? "In Progress"
            : item.review_status === "done"
              ? "Reviewed"
              : "Todo";
        metaDiv.appendChild(statusSpan);
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

  async function selectQuestion(questionId) {
    state.currentQuestionId = questionId;
    if (ui.questionSelect) {
      ui.questionSelect.value = questionId;
    }

    const question = getCurrentQuestion();
    let pageChanged = false;
    if (question && question.final) {
      const finalData = question.final;
      state.activeCoords = finalData.coords;
      const docFilename = finalData.source_file;
      const pageNum = finalData.page_number; // 1-based page number

      let targetDocIdx = state.currentDocIdx;
      if (docFilename) {
        const docs = state.currentSubmission?.documents || [];
        const foundIdx = docs.findIndex((d) => d.filename === docFilename);
        if (foundIdx >= 0) {
          targetDocIdx = foundIdx;
        }
      }

      let targetPageIdx = state.currentPageIdx;
      if (typeof pageNum === "number" && pageNum >= 1) {
        targetPageIdx = pageNum - 1;
      }

      if (targetDocIdx !== state.currentDocIdx || targetPageIdx !== state.currentPageIdx) {
        state.currentDocIdx = targetDocIdx;
        state.currentPageIdx = targetPageIdx;
        if (ui.docSelect) {
          ui.docSelect.value = String(targetDocIdx);
        }
        if (ui.pageInput) {
          ui.pageInput.value = String(targetPageIdx + 1);
        }
        try {
          pageChanged = true;
          state.scrollPending = true;
          await loadCurrentPage();
        } catch (error) {
          showToast(error.message, "error");
        }
      }
    }

    renderSubmission();
    if (!pageChanged) {
      scrollToMarker();
    }
  }

  function scrollToMarker() {
    const question = getCurrentQuestion();
    if (!question) return;
    const coords = state.activeCoords || question.final?.coords;
    if (!coords || coords.length !== 2) return;

    if (!ui.pageImage.complete || !ui.pageImage.offsetWidth || !ui.pageImage.offsetHeight) {
      return;
    }

    const y = Number(coords[0]);
    const x = Number(coords[1]);
    const px = ui.pageImage.offsetLeft + (x / 1000) * ui.pageImage.offsetWidth;
    const py = ui.pageImage.offsetTop + (y / 1000) * ui.pageImage.offsetHeight;

    ui.imageWrap.scrollTo({
      top: py - ui.imageWrap.clientHeight / 2,
      left: px - ui.imageWrap.clientWidth / 2,
      behavior: "smooth"
    });

    ui.marker.classList.remove("pulse-animation");
    void ui.marker.offsetWidth; // Force reflow
    ui.marker.classList.add("pulse-animation");
  }

  function renderQuestionNavGrid() {
    if (!ui.questionNavGrid) {
      return;
    }
    ui.questionNavGrid.innerHTML = "";
    const submission = state.currentSubmission;
    if (!submission) {
      return;
    }
    const questions = submission.questions || {};
    Object.keys(questions)
      .sort()
      .forEach((qId) => {
        const questionObj = questions[qId] || {};
        const finalData = questionObj.final || {};
        const verdict = finalData.verdict || "needs_review";

        const card = document.createElement("div");
        card.className = "question-nav-card";
        if (qId === state.currentQuestionId) {
          card.classList.add("active");
        }

        if (["correct", "rounding_error", "partial", "incorrect", "needs_review"].includes(verdict)) {
          card.classList.add(verdict);
        } else {
          card.classList.add("needs_review");
        }

        const isReviewed = !!finalData.reviewed;
        if (isReviewed) {
          card.classList.add("reviewed");
        }

        const verdictIcons = {
          correct: "✓",
          rounding_error: "≈",
          partial: "◐",
          incorrect: "✗",
          needs_review: "⟳"
        };
        const icon = verdictIcons[verdict] || "⟳";

        const labelSpan = document.createElement("span");
        labelSpan.textContent = `Q${qId}`;
        card.appendChild(labelSpan);

        const iconSpan = document.createElement("span");
        iconSpan.className = "card-icon";
        iconSpan.textContent = icon;
        card.appendChild(iconSpan);

        if (isReviewed) {
          const badge = document.createElement("span");
          badge.className = "q-check-badge";
          badge.textContent = "✓";
          card.appendChild(badge);
        }

        card.addEventListener("click", () => {
          selectQuestion(qId);
        });

        ui.questionNavGrid.appendChild(card);
      });
  }

  function renderSubmission() {
    const submission = state.currentSubmission;
    if (!submission) {
      return;
    }
    const identity = submission.identity || {};
    const summary = submission.final_summary || {};
    ui.submissionTitle.textContent = identity.student_name || "Submission";
    if (ui.summaryText) {
      ui.summaryText.textContent = `Band: ${summary.band || "—"} · Percent: ${summary.percent || 0}% · Points: ${summary.points || "—"}`;
    } else {
      ui.summaryBox.textContent = `Band: ${summary.band || "—"} · Percent: ${summary.percent || 0}% · Points: ${summary.points || "—"}`;
    }

    if (ui.submissionStatusSelect) {
      ui.submissionStatusSelect.value = submission.review_status || "todo";
    }

    renderQuestionNavGrid();

    const question = getCurrentQuestion();
    if (!question) {
      ui.marker.hidden = true;
      updateDebugOverlay(null);
      if (ui.questionReviewedCheckbox) {
        ui.questionReviewedCheckbox.checked = false;
        ui.questionReviewedCheckbox.disabled = true;
      }
      return;
    }

    const finalData = question.final || {};
    if (ui.questionReviewedCheckbox) {
      ui.questionReviewedCheckbox.checked = !!finalData.reviewed;
      ui.questionReviewedCheckbox.disabled = false;
    }

    // Judge critique logic
    const judgeCritique = question.judge_critique;
    if (judgeCritique) {
      ui.judgeCritiqueContainer.style.display = "block";
      ui.judgeCritiqueText.textContent = judgeCritique.critique;
      ui.acceptJudgeFixBtn.onclick = () => {
        ui.verdictSelect.value = judgeCritique.proposed_verdict;
        ui.reasonInput.value = judgeCritique.proposed_reason || "";
        const buttons = document.querySelectorAll("#verdictButtonRow .verdict-btn");
        buttons.forEach((btn) => {
          if (btn.dataset.verdict === judgeCritique.proposed_verdict) {
            btn.classList.add("active");
          } else {
            btn.classList.remove("active");
          }
        });
        queuePatch({ 
          verdict_final: judgeCritique.proposed_verdict,
          short_reason_final: judgeCritique.proposed_reason || ""
        }, 0);
      };
    } else {
      ui.judgeCritiqueContainer.style.display = "none";
    }

    ui.verdictSelect.value = finalData.verdict || "needs_review";
    const buttons = document.querySelectorAll("#verdictButtonRow .verdict-btn");
    buttons.forEach((btn) => {
      if (btn.dataset.verdict === (finalData.verdict || "needs_review")) {
        btn.classList.add("active");
      } else {
        btn.classList.remove("active");
      }
    });
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

    // Render subparts if present
    if (ui.subpartsContainer) {
      if (finalData.sub_results && finalData.sub_results.length > 0) {
        ui.subpartsContainer.style.display = "block";
        const subList = ui.subpartsContainer.querySelector(".subparts-list");
        if (subList) {
          subList.innerHTML = finalData.sub_results.map((sub, idx) => {
            const verdictIcon = {
              correct: "✓",
              rounding_error: "≈",
              partial: "◐",
              incorrect: "✗",
              needs_review: "⟳"
            }[sub.verdict] || "⟳";
            return `
              <div class="subpart-row" data-index="${idx}" style="cursor: pointer;">
                <span style="font-weight: 600;">${sub.id}</span>
                <span class="subpart-verdict ${sub.verdict}">
                  ${verdictIcon} ${sub.verdict.replace("_", " ")}
                </span>
                <span style="font-size: 0.85em; color: var(--text-secondary); max-width: 50%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${sub.short_reason || ""}">
                  ${sub.short_reason || ""}
                </span>
              </div>
            `;
          }).join("");

          subList.querySelectorAll(".subpart-row").forEach((row) => {
            row.addEventListener("click", async () => {
              const idx = Number(row.dataset.index);
              const sub = finalData.sub_results[idx];
              if (sub) {
                await jumpToSubpartLocation(sub);
              }
            });
          });
        }
      } else {
        ui.subpartsContainer.style.display = "none";
      }
    }

    renderMarker();
    updateDebugOverlay(finalData);
  }

  async function jumpToSubpartLocation(sub) {
    let targetDocIdx = state.currentDocIdx;
    if (sub.source_file) {
      const docs = state.currentSubmission?.documents || [];
      const foundIdx = docs.findIndex((d) => d.filename === sub.source_file);
      if (foundIdx >= 0) {
        targetDocIdx = foundIdx;
      }
    }

    let targetPageIdx = state.currentPageIdx;
    if (typeof sub.page_number === "number" && sub.page_number >= 1) {
      targetPageIdx = sub.page_number - 1;
    }

    state.activeCoords = sub.coords;

    if (targetDocIdx !== state.currentDocIdx || targetPageIdx !== state.currentPageIdx) {
      state.currentDocIdx = targetDocIdx;
      state.currentPageIdx = targetPageIdx;
      if (ui.docSelect) {
        ui.docSelect.value = String(targetDocIdx);
      }
      if (ui.pageInput) {
        ui.pageInput.value = String(targetPageIdx + 1);
      }
      try {
        await loadCurrentPage();
      } catch (error) {
        showToast(error.message, "error");
      }
    } else {
      renderMarker();
    }
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

  function getVerdictIcon(verdict) {
    const verdictIcons = {
      correct: "✓",
      rounding_error: "≈",
      partial: "◐",
      incorrect: "✗",
      needs_review: "⟳"
    };
    return verdictIcons[verdict] || "⟳";
  }

  function renderMarker() {
    ui.imageWrap.querySelectorAll('.marker.inactive').forEach(el => el.remove());
    const submission = state.currentSubmission;
    if (!submission) {
      ui.marker.hidden = true;
      return;
    }
    const currentDocFilename = submission.documents?.[state.currentDocIdx]?.filename;
    const questions = submission.questions || {};
    const imgRect = ui.pageImage.getBoundingClientRect();
    const wrapRect = ui.imageWrap.getBoundingClientRect();
    if (!imgRect.width || !imgRect.height) {
      ui.marker.hidden = true;
      return;
    }
    
    Object.entries(questions).forEach(([qId, qObj]) => {
      if (qId === state.currentQuestionId) return;
      const finalData = qObj.final || {};
      const coords = finalData.coords;
      const pageNum = finalData.page_number;
      const sourceFile = finalData.source_file;
      if (coords && coords.length === 2 && pageNum - 1 === state.currentPageIdx) {
        if (!sourceFile || sourceFile === currentDocFilename) {
          const m = document.createElement("div");
          m.className = `marker inactive marker-${finalData.verdict || "needs_review"}`;
          m.textContent = getVerdictIcon(finalData.verdict);
          const y = Number(coords[0]);
          const x = Number(coords[1]);
          const px = (x / 1000) * imgRect.width;
          const py = (y / 1000) * imgRect.height;
          m.style.left = `${imgRect.left - wrapRect.left + px}px`;
          m.style.top = `${imgRect.top - wrapRect.top + py}px`;
          m.addEventListener("click", (e) => {
            e.stopPropagation();
            selectQuestion(qId);
          });
          ui.imageWrap.appendChild(m);
        }
      }
    });

    const question = getCurrentQuestion();
    if (!question) {
      ui.marker.hidden = true;
      return;
    }
    const coords = state.activeCoords || question.final?.coords;
    if (!coords || coords.length !== 2) {
      ui.marker.hidden = true;
      if (ui.xCoordInput) ui.xCoordInput.value = "";
      if (ui.yCoordInput) ui.yCoordInput.value = "";
      return;
    }

    const verdict = question.final?.verdict || "needs_review";
    ui.marker.className = `marker marker-${verdict}`;
    
    let iconSpan = ui.marker.querySelector('.marker-icon');
    if (!iconSpan) {
      iconSpan = document.createElement('span');
      iconSpan.className = 'marker-icon';
      ui.marker.insertBefore(iconSpan, ui.marker.firstChild);
    }
    iconSpan.textContent = getVerdictIcon(verdict);
    
    const y = Number(coords[0]);
    const x = Number(coords[1]);
    const px = (x / 1000) * imgRect.width;
    const py = (y / 1000) * imgRect.height;
    ui.marker.style.left = `${imgRect.left - wrapRect.left + px}px`;
    ui.marker.style.top = `${imgRect.top - wrapRect.top + py}px`;
    ui.marker.hidden = false;
    
    if (ui.xCoordInput) ui.xCoordInput.value = Math.round(x);
    if (ui.yCoordInput) ui.yCoordInput.value = Math.round(y);
    if (ui.markerLabel) ui.markerLabel.textContent = `Page ${state.currentPageIdx + 1}, (${Math.round(x)}, ${Math.round(y)})`;
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

  // --- Matrix helpers ---

  async function loadMatrix() {
    state.matrixData = await apiGet("/api/matrix");
    renderMatrix();
  }

  function renderMatrix() {
    if (!state.matrixData || !ui.matrixGrid) return;
    
    const { question_ids, students, hotspots } = state.matrixData;
    
    // sorting
    const sortBy = ui.matrixSortSelect ? ui.matrixSortSelect.value : "name";
    let sortedStudents = [...students];
    if (sortBy === "percent") {
      sortedStudents.sort((a, b) => b.percent - a.percent);
    } else if (sortBy === "band") {
      // simple alpha sort for band
      sortedStudents.sort((a, b) => String(a.band).localeCompare(String(b.band)));
    } else {
      sortedStudents.sort((a, b) => String(a.student_name).localeCompare(String(b.student_name)));
    }
    
    // filtering
    const anomaliesOnly = ui.matrixFilterToggle && ui.matrixFilterToggle.checked;
    
    // prepare hotspots sets
    const lowPassQuestions = new Set();
    const inconsistencies = new Set();
    const borderlineFolders = new Set();
    
    if (hotspots) {
      (hotspots.question_stats || []).forEach(qs => {
        if (qs.pass_rate < 0.3) lowPassQuestions.add(qs.question_id);
      });
      (hotspots.inconsistencies || []).forEach(inc => {
        inconsistencies.add(`${inc.student_a}|${inc.question_id}`);
        inconsistencies.add(`${inc.student_b}|${inc.question_id}`);
      });
      (hotspots.borderline_students || []).forEach(bs => {
        borderlineFolders.add(bs.folder);
      });
    }

    if (anomaliesOnly) {
      sortedStudents = sortedStudents.filter(s => {
        if (borderlineFolders.has(s.folder)) return true;
        for (const qId of question_ids) {
          if (inconsistencies.has(`${s.student_name}|${qId}`)) return true;
          if (lowPassQuestions.has(qId) && s.cells[qId]?.verdict !== "correct") return true;
          if (s.cells[qId]?.verdict === "needs_review") return true;
        }
        return false;
      });
    }

    ui.matrixGrid.innerHTML = "";
    ui.matrixGrid.style.gridTemplateColumns = `max-content repeat(${question_ids.length}, minmax(40px, 1fr))`;
    
    // Header row
    const corner = document.createElement("div");
    corner.className = "matrix-header-cell matrix-corner";
    ui.matrixGrid.appendChild(corner);
    
    question_ids.forEach(qId => {
      const th = document.createElement("div");
      th.className = "matrix-header-cell";
      th.textContent = qId;
      if (lowPassQuestions.has(qId)) {
        th.classList.add("hotspot-fail");
      }
      ui.matrixGrid.appendChild(th);
    });

    // Student rows
    sortedStudents.forEach(student => {
      const rowHeader = document.createElement("div");
      rowHeader.className = "matrix-row-header";
      rowHeader.textContent = student.student_name || student.folder;
      
      const bandClass = bandBadgeClass(student.band);
      rowHeader.classList.add(bandClass.replace("badge", "").trim() || "badge-default");
      
      if (borderlineFolders.has(student.folder)) {
        rowHeader.classList.add("hotspot-borderline");
      }
      ui.matrixGrid.appendChild(rowHeader);
      
      question_ids.forEach(qId => {
        const cellData = student.cells[qId] || {};
        const cell = document.createElement("div");
        cell.className = "matrix-cell";
        
        let verdictSym = "⟳";
        let vClass = "cell-needs-review";
        if (cellData.verdict === "correct") { verdictSym = "✓"; vClass = "cell-correct"; }
        else if (cellData.verdict === "rounding_error") { verdictSym = "≈"; vClass = "cell-rounding"; }
        else if (cellData.verdict === "partial") { verdictSym = "◐"; vClass = "cell-partial"; }
        else if (cellData.verdict === "incorrect") { verdictSym = "✗"; vClass = "cell-incorrect"; }
        
        cell.classList.add(vClass);
        const conf = cellData.confidence !== undefined ? cellData.confidence : 1.0;
        cell.style.opacity = Math.max(0.2, 0.4 + (conf * 0.6));
        
        if (inconsistencies.has(`${student.student_name}|${qId}`)) {
          cell.classList.add("hotspot-inconsistency");
        }
        
        if (cellData.judge_critique && cellData.judge_critique.proposed_verdict !== cellData.verdict) {
          cell.style.border = "2px dotted #e53e3e";
        }
        
        cell.textContent = verdictSym;
        if (cellData.grading_source === "regex" || cellData.grading_source === "sub_regex") {
          const icon = document.createElement("span");
          icon.className = "matrix-regex-icon";
          icon.textContent = "🧪";
          cell.appendChild(icon);
        }
        if (cellData.reviewed) {
          cell.classList.add("matrix-cell-reviewed");
          const badge = document.createElement("span");
          badge.className = "matrix-reviewed-badge";
          badge.textContent = "✓";
          cell.appendChild(badge);
        }
        
        cell.addEventListener("click", () => showMatrixDetail(student, qId, cellData));
        ui.matrixGrid.appendChild(cell);
      });
    });
  }

  function showMatrixDetail(student, qId, cellData) {
    if (!ui.matrixDetail) return;
    
    const confPercent = Math.round((cellData.confidence || 0) * 100);
    const sourceIcon = (cellData.grading_source === "regex" || cellData.grading_source === "sub_regex") ? "🧪 Regex" : "🤖 LLM";
    
    let verdictLabel = "Needs Review";
    if (cellData.verdict === "correct") verdictLabel = "Correct";
    else if (cellData.verdict === "rounding_error") verdictLabel = "Rounding Error";
    else if (cellData.verdict === "partial") verdictLabel = "Partial";
    else if (cellData.verdict === "incorrect") verdictLabel = "Incorrect";
    
    ui.matrixDetail.innerHTML = `
      <div class="mdetail-header">
        <h3>${student.student_name || student.folder}</h3>
        <div class="mdetail-meta">${bandLabel(student.band)} · ${student.percent}%</div>
      </div>
      <div class="mdetail-section">
        <h4>Question ${qId}</h4>
        <div class="mdetail-verdict ${cellData.verdict}">${verdictLabel} <span class="mdetail-conf">(${confPercent}% conf, ${sourceIcon})</span></div>
      </div>
      <div class="mdetail-section">
        <h4>Evidence Quote</h4>
        <div class="mdetail-quote">${cellData.evidence_quote || "<em>None</em>"}</div>
      </div>
      <div class="mdetail-section">
        <h4>Logic Analysis</h4>
        <div class="mdetail-logic">${cellData.logic_analysis || "<em>None</em>"}</div>
      </div>
      <div class="mdetail-actions">
        <div class="checkbox-container-custom" style="margin-top: 0.5rem; margin-bottom: 0.5rem;">
          <input type="checkbox" id="mdetailReviewedToggle" ${cellData.reviewed ? "checked" : ""} />
          <label for="mdetailReviewedToggle">Reviewed</label>
        </div>
        <button id="mdetailJumpBtn" type="button" class="btn-primary">Jump to Review</button>
      </div>
    `;
    
    const reviewedToggle = document.getElementById("mdetailReviewedToggle");
    reviewedToggle.addEventListener("change", async () => {
      try {
        await apiPatch(`/api/submissions/${student.submission_id}/questions/${qId}`, { reviewed_final: reviewedToggle.checked });
        cellData.reviewed = reviewedToggle.checked;
        renderMatrix();
      } catch (err) {
        showToast(err.message, "error");
        reviewedToggle.checked = !reviewedToggle.checked;
      }
    });
    
    document.getElementById("mdetailJumpBtn").addEventListener("click", () => {
      setTab("review");
      selectSubmission(student.submission_id).then(() => {
        state.currentQuestionId = qId;
        renderSubmission();
        buildQuestionSelect();
      });
    });
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
    if (ui.tabMatrixBtn) {
      ui.tabMatrixBtn.addEventListener("click", () => {
        setTab("matrix");
      });
    }

    if (ui.tabSetupBtn) {
      ui.tabSetupBtn.addEventListener("click", () => {
        setTab("setup");
      });
    }

    if (ui.debugOverlayToggle) {
      ui.debugOverlayToggle.addEventListener("change", () => {
        const question = getCurrentQuestion();
        updateDebugOverlay(question?.final || null);
      });
    }

    if (ui.matrixSortSelect) ui.matrixSortSelect.addEventListener("change", renderMatrix);
    if (ui.matrixFilterToggle) ui.matrixFilterToggle.addEventListener("change", renderMatrix);

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

    ui.exportBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      if (ui.exportMenu) {
        ui.exportMenu.classList.toggle("hidden");
      }
    });

    document.addEventListener("click", (e) => {
      if (ui.exportDropdown && !ui.exportDropdown.contains(e.target) && ui.exportMenu) {
        ui.exportMenu.classList.add("hidden");
      }
    });

    async function triggerExportDownload(endpoint, description) {
      if (ui.exportMenu) {
        ui.exportMenu.classList.add("hidden");
      }
      await flushPatch();
      await flushNote();
      showToast(`Preparing ${description} download…`, "info");
      window.location.href = endpoint;
    }

    if (ui.exportCsvBtn) {
      ui.exportCsvBtn.addEventListener("click", () => {
        triggerExportDownload("/api/export/csv", "Brightspace CSV").catch((e) => {
          showToast(`Export failed: ${e.message}`, "error");
        });
      });
    }

    if (ui.exportAuditBtn) {
      ui.exportAuditBtn.addEventListener("click", () => {
        triggerExportDownload("/api/export/audit", "Audit CSV").catch((e) => {
          showToast(`Export failed: ${e.message}`, "error");
        });
      });
    }

    if (ui.exportPdfsBtn) {
      ui.exportPdfsBtn.addEventListener("click", () => {
        triggerExportDownload("/api/export/pdfs", "Reviewed PDFs ZIP").catch((e) => {
          showToast(`Export failed: ${e.message}`, "error");
        });
      });
    }

    if (ui.exportBundleBtn) {
      ui.exportBundleBtn.addEventListener("click", () => {
        triggerExportDownload("/api/export/bundle", "Complete Export Bundle ZIP").catch((e) => {
          showToast(`Export failed: ${e.message}`, "error");
        });
      });
    }

    if (ui.exportServerBtn) {
      ui.exportServerBtn.addEventListener("click", async () => {
        if (ui.exportMenu) {
          ui.exportMenu.classList.add("hidden");
        }
        await flushPatch();
        await flushNote();
        try {
          const result = await apiPost("/api/export", {});
          const artifacts = result.artifacts || {};
          const artifactLines = Object.entries(artifacts)
            .map(([name, path]) => `• ${name}: ${path}`)
            .join("\n");
          showToast(`Export complete!\n${artifactLines}`, "success");
          if (artifacts["Reviewed PDFs folder"]) {
            setStatus(`Reviewed PDFs: ${artifacts["Reviewed PDFs folder"]}`);
          }
        } catch (e) {
          showToast(`Export failed: ${e.message}`, "error");
        }
      });
    }

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
      if (state.scrollPending) {
        state.scrollPending = false;
        scrollToMarker();
      }
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

    ui.verdictSelect.addEventListener("change", () => {
      const val = ui.verdictSelect.value;
      const reason = ui.reasonInput ? ui.reasonInput.value.trim() : "";
      if ((val === "incorrect" || val === "partial") && !reason) {
        showToast("A short reason is required for incorrect or partial verdicts.", "error");
        const question = getCurrentQuestion();
        ui.verdictSelect.value = question?.final?.verdict || "needs_review";
        return;
      }
      queuePatch({ verdict_final: val }, 150);
      const buttons = document.querySelectorAll("#verdictButtonRow .verdict-btn");
      buttons.forEach((btn) => {
        if (btn.dataset.verdict === val) {
          btn.classList.add("active");
        } else {
          btn.classList.remove("active");
        }
      });
    });

    const verdictBtns = document.querySelectorAll("#verdictButtonRow .verdict-btn");
    verdictBtns.forEach((btn) => {
      btn.addEventListener("click", () => {
        const verdict = btn.dataset.verdict;
        const reason = ui.reasonInput ? ui.reasonInput.value.trim() : "";
        if ((verdict === "incorrect" || verdict === "partial") && !reason) {
          showToast("A short reason is required for incorrect or partial verdicts.", "error");
          return;
        }
        
        const question = getCurrentQuestion();
        if (question) {
          if (!question.final) {
            question.final = {};
          }
          question.final.verdict = verdict;
          question.final.reviewed = true;
          
          if (ui.verdictSelect) {
            ui.verdictSelect.value = verdict;
          }
          if (ui.questionReviewedCheckbox) {
            ui.questionReviewedCheckbox.checked = true;
            ui.questionReviewedCheckbox.disabled = false;
          }

          const buttons = document.querySelectorAll("#verdictButtonRow .verdict-btn");
          buttons.forEach((b) => {
            if (b.dataset.verdict === verdict) {
              b.classList.add("active");
            } else {
              b.classList.remove("active");
            }
          });

          renderQuestionNavGrid();
          queuePatch({ verdict_final: verdict, reviewed_final: true }, 150);

          const autoAdvanceToggle = document.getElementById("autoAdvanceToggle");
          if (autoAdvanceToggle && autoAdvanceToggle.checked) {
            const questionIds = Object.keys(state.currentSubmission.questions).sort();
            const currentIdx = questionIds.indexOf(state.currentQuestionId);
            let nextQId = null;
            for (let i = 1; i <= questionIds.length; i++) {
              const idx = (currentIdx + i) % questionIds.length;
              const qId = questionIds[idx];
              const q = state.currentSubmission.questions[qId];
              if (!q.final || !q.final.reviewed) {
                nextQId = qId;
                break;
              }
            }
            if (nextQId) {
              setTimeout(() => {
                selectQuestion(nextQId);
              }, 200);
            }
          }
        }
      });
    });
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
      const num = raw === "" ? null : Number(raw);
      if (num !== null && (isNaN(num) || num < 1)) {
        return;
      }
      queuePatch({ page_final: num }, 500);
      const question = getCurrentQuestion();
      if (question) {
        question.final.page_number = num;
      }
    });

    if (ui.xCoordInput && ui.yCoordInput) {
      const handleCoordInput = () => {
        const x = parseFloat(ui.xCoordInput.value);
        const y = parseFloat(ui.yCoordInput.value);
        if (!isNaN(x) && !isNaN(y)) {
          const coords = [Math.max(0, Math.min(1000, y)), Math.max(0, Math.min(1000, x))];
          state.activeCoords = coords;
          const question = getCurrentQuestion();
          if (question) {
            if (!question.final) question.final = {};
            question.final.coords = coords;
          }
          renderMarker();
          queuePatch({ coords_final: coords }, 250);
        }
      };
      ui.xCoordInput.addEventListener("input", handleCoordInput);
      ui.yCoordInput.addEventListener("input", handleCoordInput);
    }

    if (ui.questionReviewedCheckbox) {
      ui.questionReviewedCheckbox.addEventListener("change", () => {
        const question = getCurrentQuestion();
        if (question) {
          if (!question.final) {
            question.final = {};
          }
          question.final.reviewed = ui.questionReviewedCheckbox.checked;
          renderQuestionNavGrid();
          queuePatch({ reviewed_final: ui.questionReviewedCheckbox.checked }, 150);
        }
      });
    }

    ui.noteInput.addEventListener("input", () => queueNoteSave(600));
    ui.noteInput.addEventListener("blur", () => {
      flushNote().catch((error) => showToast(error.message, "error"));
    });

    if (ui.submissionStatusSelect) {
      ui.submissionStatusSelect.addEventListener("change", async () => {
        const submission = state.currentSubmission;
        if (!submission) return;

        const newValue = ui.submissionStatusSelect.value;
        const oldValue = submission.review_status || "todo";

        if (newValue === "done") {
          const needsReviewCount = Object.values(submission.questions || {}).filter(
            (q) => q?.final?.verdict === "needs_review"
          ).length;

          if (needsReviewCount > 0) {
            const confirmed = confirm(
              "This submission has unresolved questions. It will be exported to Brightspace as REVIEW_REQUIRED (no points). Are you sure you want to mark this as Done?"
            );
            if (!confirmed) {
              ui.submissionStatusSelect.value = oldValue;
              return;
            }
          }
        }

        try {
          const res = await apiPatch(`/api/submissions/${submission.submission_id}`, {
            review_status: newValue,
          });
          submission.review_status = res.review_status;
          const queueItem = state.submissions.find((s) => s.submission_id === submission.submission_id);
          if (queueItem) {
            queueItem.review_status = res.review_status;
          }
          renderQueue();
          renderSubmission();
          showToast(`Submission review status updated to: ${newValue === "done" ? "Reviewed" : newValue}`, "success");
        } catch (error) {
          showToast(error.message, "error");
          ui.submissionStatusSelect.value = oldValue;
        }
      });
    }

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
        state.activeCoords = coords;
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
        state.activeCoords = coords;
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

  function initSetupUI() {
    const profileInput = document.getElementById("setupProfileName");
    const gradeColumnSelect = document.getElementById("setupGradeColumn");
    const generateBtn = document.getElementById("btnGenerateRubric");
    
    const setupDropZones = [
      { id: "dropSubmissions", fileId: "fileSubmissions", formKey: "submissions_zip" },
      { id: "dropSolutions", fileId: "fileSolutions", formKey: "solutions_pdf" },
      { id: "dropRubric", fileId: "fileRubric", formKey: "rubric_yaml" },
      { id: "dropGradesCsv", fileId: "fileGradesCsv", formKey: "grades_template_csv" },
    ];
    
    setupDropZones.forEach(zone => {
      const dropEl = document.getElementById(zone.id);
      const fileInput = document.getElementById(zone.fileId);
      const statusEl = document.getElementById(zone.id.replace("drop", "status"));
      if(!dropEl) return;
      
      dropEl.addEventListener("dragover", e => {
        e.preventDefault();
        dropEl.classList.add("dragover");
      });
      dropEl.addEventListener("dragleave", e => {
        e.preventDefault();
        dropEl.classList.remove("dragover");
      });
      dropEl.addEventListener("drop", e => {
        e.preventDefault();
        dropEl.classList.remove("dragover");
        if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
          handleSetupUpload(zone, e.dataTransfer.files[0], dropEl, statusEl);
        }
      });
      dropEl.addEventListener("click", () => fileInput.click());
      fileInput.addEventListener("change", () => {
        if (fileInput.files.length > 0) {
          handleSetupUpload(zone, fileInput.files[0], dropEl, statusEl);
        }
      });
    });
    
    async function handleSetupUpload(zone, file, dropEl, statusEl) {
      const profile = profileInput.value.trim();
      if (!profile) {
        showToast("Please enter a Profile Name first", "error");
        return;
      }
      
      statusEl.textContent = `Uploading ${file.name}...`;
      const formData = new FormData();
      formData.append("profile", profile);
      formData.append(zone.formKey, file);
      
      try {
        const res = await fetch("/api/setup/upload", { method: "POST", body: formData });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Upload failed");
        
        statusEl.textContent = `✓ Uploaded ${file.name}`;
        dropEl.classList.add("success");
        
        if (zone.formKey === "grades_template_csv" && data.uploaded.csv_headers) {
          gradeColumnSelect.innerHTML = "";
          data.uploaded.csv_headers.forEach(h => {
            const opt = document.createElement("option");
            opt.value = h;
            opt.textContent = h;
            if (h.toLowerCase().includes("grade") || h.toLowerCase().includes("score")) {
              opt.selected = true;
            }
            gradeColumnSelect.appendChild(opt);
          });
        }
        
        if (zone.formKey === "solutions_pdf") {
          generateBtn.style.display = "inline-block";
        }
        
        showToast(`Successfully uploaded ${zone.formKey}`, "success");
      } catch (err) {
        statusEl.textContent = `Error: ${err.message}`;
        showToast(err.message, "error");
      }
    }
    
    if(generateBtn) {
      generateBtn.addEventListener("click", async (e) => {
        e.stopPropagation();
        const profile = profileInput.value.trim();
        if (!profile) return;
        
        generateBtn.textContent = "Generating... (takes ~30s)";
        generateBtn.disabled = true;
        try {
          await apiPost("/api/setup/rubric/generate", { profile });
          showToast("Draft rubric generated & saved!", "success");
          document.getElementById("dropRubric").classList.add("success");
          document.getElementById("statusRubric").textContent = "✓ AI Rubric generated";
        } catch(err) {
          showToast(err.message, "error");
        } finally {
          generateBtn.textContent = "Generate AI Rubric";
          generateBtn.disabled = false;
        }
      });
    }
    
    const saveBtn = document.getElementById("saveProfileBtn");
    if(saveBtn) {
      saveBtn.addEventListener("click", async () => {
        const profile = profileInput.value.trim();
        if (!profile) {
          showToast("Enter a profile name", "error"); return;
        }
        try {
          await apiPost("/api/setup/profile", {
            profile,
            model: document.getElementById("setupModel").value,
            concurrency: Number(document.getElementById("setupConcurrency").value),
            grade_column: gradeColumnSelect.value,
            check_plus_points: document.getElementById("setupCheckPlus").value,
            check_points: document.getElementById("setupCheck").value,
            check_minus_points: document.getElementById("setupCheckMinus").value,
            review_required_points: document.getElementById("setupReviewRequired").value,
          });
          showToast("Profile saved!", "success");
        } catch (err) {
          showToast(err.message, "error");
        }
      });
    }

    const saveGradeBtn = document.getElementById("saveAndGradeBtn");
    if(saveGradeBtn) {
      saveGradeBtn.addEventListener("click", async () => {
        const profile = profileInput.value.trim();
        if (!profile) {
          showToast("Enter a profile name", "error"); return;
        }
        
        // First save the profile
        try {
          await apiPost("/api/setup/profile", {
            profile,
            model: document.getElementById("setupModel").value,
            concurrency: Number(document.getElementById("setupConcurrency").value),
            grade_column: gradeColumnSelect.value,
            check_plus_points: document.getElementById("setupCheckPlus").value,
            check_points: document.getElementById("setupCheck").value,
            check_minus_points: document.getElementById("setupCheckMinus").value,
            review_required_points: document.getElementById("setupReviewRequired").value,
          });
        } catch (err) {
          showToast(`Save failed: ${err.message}`, "error");
          return;
        }

        // Then start grading
        try {
          await apiPost("/api/grade/start", { profile });
          startSseStream();
        } catch (err) {
          showToast(`Failed to start grading: ${err.message}`, "error");
        }
      });
    }

    // Modal UI elements
    const gradingModal = document.getElementById("gradingProgressModal");
    const gradingStatusText = document.getElementById("gradingStatusText");
    const gradingProgressBar = document.getElementById("gradingProgressBar");
    const gradingProgressDetails = document.getElementById("gradingProgressDetails");
    const cancelGradingBtn = document.getElementById("cancelGradingBtn");
    const closeGradingModalBtn = document.getElementById("closeGradingModalBtn");
    
    let eventSource = null;

    function logProgress(msg) {
      const div = document.createElement("div");
      div.textContent = msg;
      gradingProgressDetails.appendChild(div);
      gradingProgressDetails.scrollTop = gradingProgressDetails.scrollHeight;
    }

    function startSseStream() {
      gradingModal.classList.remove("hidden");
      gradingStatusText.textContent = "Connecting...";
      gradingProgressBar.style.width = "0%";
      gradingProgressDetails.innerHTML = "";
      cancelGradingBtn.style.display = "inline-block";
      closeGradingModalBtn.style.display = "none";
      
      if (eventSource) {
        eventSource.close();
      }
      
      eventSource = new EventSource("/api/grade/progress");
      
      eventSource.onopen = () => {
        gradingStatusText.textContent = "Grading in progress...";
        logProgress("Connected to grading stream.");
      };

      eventSource.addEventListener("info", (e) => {
        const data = JSON.parse(e.data);
        logProgress(`[INFO] ${data.message}`);
      });

      eventSource.addEventListener("warning", (e) => {
        const data = JSON.parse(e.data);
        logProgress(`[WARN] ${data.message}`);
      });

      eventSource.addEventListener("error", (e) => {
        const data = JSON.parse(e.data);
        logProgress(`[ERROR] ${data.message}`);
      });

      eventSource.addEventListener("progress_start", (e) => {
        const data = JSON.parse(e.data);
        logProgress(`Grading batch of ${data.total} submissions started.`);
      });

      eventSource.addEventListener("progress", (e) => {
        const data = JSON.parse(e.data);
        if (data.status === "started") {
          gradingStatusText.textContent = `Grading: ${data.folder_name} (${data.index}/${data.total})`;
        } else if (data.status === "finished") {
          logProgress(`Finished ${data.folder_name} -> ${data.band} (${data.elapsed_seconds || 0}s)`);
          const pct = Math.round((data.index / data.total) * 100);
          gradingProgressBar.style.width = `${pct}%`;
        }
      });

      eventSource.addEventListener("status", (e) => {
        const data = JSON.parse(e.data);
        logProgress(data.message);
      });

      eventSource.addEventListener("complete", (e) => {
        const data = JSON.parse(e.data);
        logProgress(`[COMPLETE] ${data.message}`);
        gradingStatusText.textContent = "Grading Completed!";
        gradingProgressBar.style.width = "100%";
        cancelGradingBtn.style.display = "none";
        closeGradingModalBtn.style.display = "inline-block";
        eventSource.close();
        
        // Refresh everything to show new grades
        refreshRun();
        refreshQueue();
      });

      eventSource.onerror = (e) => {
        logProgress(`[CONNECTION ERROR] Stream disconnected.`);
        eventSource.close();
        cancelGradingBtn.style.display = "none";
        closeGradingModalBtn.style.display = "inline-block";
      };
    }

    if (cancelGradingBtn) {
      cancelGradingBtn.addEventListener("click", async () => {
        try {
          await apiPost("/api/grade/cancel", {});
          cancelGradingBtn.disabled = true;
          cancelGradingBtn.textContent = "Cancelling...";
          logProgress("Cancellation requested...");
        } catch (err) {
          showToast(`Cancel failed: ${err.message}`, "error");
        }
      });
    }

    if (closeGradingModalBtn) {
      closeGradingModalBtn.addEventListener("click", () => {
        gradingModal.classList.add("hidden");
        // Ensure UI is refreshed if they closed without completion
        refreshRun();
        refreshQueue();
      });
    }

    // Check if grading is already running when page loads
    apiGet("/api/grade/status").then((status) => {
      if (status.state === "running") {
        startSseStream();
      }
    }).catch(() => {});
  }

  async function init() {
    bindEvents();
    initSetupUI();
    setTab("review");
    await refreshRun();
    await refreshQueue();
    if (state.submissions.length > 0) {
      await selectSubmission(state.submissions[0].submission_id);
      renderQueue();
    } else {
      setTab("setup");
    }
  }

  init().catch((error) => {
    setStatus(`Failed to initialize: ${error.message}`);
    showToast(error.message, "error");
  });
})();
