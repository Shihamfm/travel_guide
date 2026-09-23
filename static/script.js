/**
 * TripMate AI — Multi-Agent Travel Planner
 * Frontend Logic Engine (script.js v3.0)
 */

let currentThreadId = localStorage.getItem("travel_thread_id") || null;
let latestTravelData = null;

// Initialize app state on load
document.addEventListener("DOMContentLoaded", () => {
    updateThreadBar(currentThreadId);
    checkBackendHealth();
});

/**
 * Check backend connection status
 */
async function checkBackendHealth() {
    const statusPill = document.getElementById("backendStatus");
    try {
        const response = await fetch("/health");
        if (response.ok) {
            statusPill.classList.remove("offline");
            statusPill.classList.add("online");
            statusPill.querySelector("span:last-child").textContent = "Backend Connected";
        } else {
            throw new Error("Health check failed");
        }
    } catch (e) {
        statusPill.classList.add("offline");
        statusPill.querySelector("span:last-child").textContent = "Offline Mode";
    }
}

/**
 * Update Thread Bar in top header
 */
function updateThreadBar(threadId) {
    const threadBar = document.getElementById("threadBar");
    const activeThreadId = document.getElementById("activeThreadId");

    if (threadId) {
        currentThreadId = threadId;
        localStorage.setItem("travel_thread_id", threadId);
        activeThreadId.textContent = threadId.length > 18 ? threadId.substring(0, 18) + "..." : threadId;
        activeThreadId.title = threadId;
        threadBar.classList.remove("hidden");
    } else {
        currentThreadId = null;
        localStorage.removeItem("travel_thread_id");
        threadBar.classList.add("hidden");
    }
}

/**
 * Reset travel session (Start a new trip)
 */
function resetTripSession() {
    localStorage.removeItem("travel_thread_id");
    currentThreadId = null;
    latestTravelData = null;

    document.getElementById("userInput").value = "";
    hideError();
    hideElement("guardrailBox");
    hideElement("approvalCard");
    hideElement("tripContextSection");
    hideElement("resultSection");
    hideElement("progressPipeline");
    updateThreadBar(null);

    showToast("Started a new travel planning session.", "info");
}

/**
 * Set quick prompt from popular destination cards
 */
function setPrompt(text) {
    const input = document.getElementById("userInput");
    input.value = text;
    input.focus();
    input.scrollIntoView({ behavior: "smooth", block: "center" });
    showToast("Prompt copied to input!", "info");
}

/**
 * UI Loading state helper
 */
function setLoading(isLoading, stage = "supervisor") {
    const sendBtn = document.getElementById("sendBtn");
    const btnText = document.getElementById("btnText");
    const btnLoader = document.getElementById("btnLoader");
    const pipeline = document.getElementById("progressPipeline");

    sendBtn.disabled = isLoading;

    if (isLoading) {
        btnText.classList.add("hidden");
        btnLoader.classList.remove("hidden");
        pipeline.classList.remove("hidden");
        updatePipelineStage(stage);
    } else {
        btnText.classList.remove("hidden");
        btnLoader.classList.add("hidden");
    }
}

/**
 * Update step progress pipeline visualizer
 */
function updatePipelineStage(stage) {
    const steps = ["supervisor", "specialists", "itinerary", "approval"];
    const stageIndex = steps.indexOf(stage);

    steps.forEach((s, idx) => {
        const elem = document.getElementById(`step-${s}`);
        if (!elem) return;
        elem.classList.remove("active", "completed");

        if (idx < stageIndex) {
            elem.classList.add("completed");
        } else if (idx === stageIndex) {
            elem.classList.add("active");
        }
    });
}

/**
 * Show error banner
 */
function showError(message) {
    const errorBox = document.getElementById("errorBox");
    errorBox.textContent = `⚠️ Error: ${message}`;
    errorBox.classList.remove("hidden");
    errorBox.scrollIntoView({ behavior: "smooth", block: "center" });
}

/**
 * Hide error banner
 */
function hideError() {
    const errorBox = document.getElementById("errorBox");
    errorBox.classList.add("hidden");
    errorBox.textContent = "";
}

/**
 * Show floating toast notification
 */
function showToast(message, type = "success") {
    const container = document.getElementById("toastContainer");
    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `<span>${message}</span>`;

    container.appendChild(toast);

    setTimeout(() => {
        toast.classList.add("show");
    }, 10);

    setTimeout(() => {
        toast.classList.remove("show");
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

/**
 * Render Markdown helper with fallback
 */
function renderMarkdown(content, targetElem) {
    if (!targetElem) return;
    if (!content || !content.trim()) {
        targetElem.innerHTML = "<p class='empty-msg'>No data provided by agent.</p>";
        return;
    }

    if (typeof marked !== "undefined") {
        try {
            targetElem.innerHTML = marked.parse(content);
            return;
        } catch (e) {
            console.warn("Marked parsing error:", e);
        }
    }
    targetElem.innerText = content;
}

/**
 * Copy Thread ID
 */
function copyThreadId() {
    if (!currentThreadId) return;
    navigator.clipboard.writeText(currentThreadId)
        .then(() => showToast("Thread ID copied to clipboard!", "success"))
        .catch(() => showToast("Failed to copy Thread ID.", "error"));
}

/**
 * Send primary travel message
 */
async function sendMessage() {
    hideError();
    hideElement("guardrailBox");

    const input = document.getElementById("userInput");
    const message = input.value.trim();

    if (!message) {
        showError("Please enter your travel request before generating a plan.");
        return;
    }

    setLoading(true, "supervisor");

    // Simulate pipeline stage progression visually
    const timer1 = setTimeout(() => updatePipelineStage("specialists"), 1200);
    const timer2 = setTimeout(() => updatePipelineStage("itinerary"), 3200);

    try {
        const response = await fetch("/api/travel", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                message: message,
                thread_id: currentThreadId
            })
        });

        clearTimeout(timer1);
        clearTimeout(timer2);

        const data = await response.json();

        if (!response.ok || !data.success) {
            throw new Error(data.error || "Failed to communicate with travel planner backend.");
        }

        latestTravelData = data;
        updateThreadBar(data.thread_id);
        renderTravelData(data);

    } catch (error) {
        clearTimeout(timer1);
        clearTimeout(timer2);
        showError(error.message);
        hideElement("progressPipeline");
    } finally {
        setLoading(false);
    }
}

/**
 * Toggle HITL revision box
 */
function toggleRevisionBox() {
    const container = document.getElementById("revisionContainer");
    const feedbackInput = document.getElementById("feedbackInput");
    const isHidden = container.classList.contains("hidden");

    if (isHidden) {
        container.classList.remove("hidden");
        feedbackInput.focus();
    } else {
        container.classList.add("hidden");
    }
}

/**
 * Submit Human Approval / Revision feedback
 */
async function submitApproval(approved) {
    hideError();

    const feedbackInput = document.getElementById("feedbackInput");
    const feedback = feedbackInput ? feedbackInput.value.trim() : "";

    if (!approved && !feedback) {
        showError("Please provide revision feedback explaining what changes you'd like.");
        return;
    }

    if (!currentThreadId) {
        showError("Active Thread ID missing. Please generate a new trip first.");
        return;
    }

    const approveBtn = document.querySelector(".approve-btn");
    const revisionBtn = document.querySelector(".submit-feedback-btn");
    
    if (approveBtn) approveBtn.disabled = true;
    if (revisionBtn) revisionBtn.disabled = true;

    setLoading(true, "approval");

    try {
        const response = await fetch("/api/travel/approve", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                thread_id: currentThreadId,
                approved: approved,
                feedback: feedback
            })
        });

        const data = await response.json();

        if (!response.ok || !data.success) {
            throw new Error(data.error || "Failed to submit approval choice.");
        }

        latestTravelData = data;
        showToast(approved ? "Itinerary approved! Generating final plan..." : "Revision feedback sent to AI agents!", "success");

        if (feedbackInput) feedbackInput.value = "";
        hideElement("revisionContainer");

        renderTravelData(data);

    } catch (error) {
        showError(error.message);
    } finally {
        setLoading(false);
        if (approveBtn) approveBtn.disabled = false;
        if (revisionBtn) revisionBtn.disabled = false;
    }
}

/**
 * Render all agent outputs, guardrails, HITL state, and tab content
 */
function renderTravelData(data) {
    // 1. Guardrail Check
    if (data.guardrail_allowed === false) {
        const guardrailReason = document.getElementById("guardrailReason");
        if (guardrailReason) {
            guardrailReason.textContent = data.guardrail_reason || "This request was flagged by input guardrails.";
        }
        showElement("guardrailBox");
        hideElement("approvalCard");
        hideElement("tripContextSection");
        hideElement("resultSection");
        hideElement("progressPipeline");
        return;
    }
    hideElement("guardrailBox");

    // 2. Human In The Loop (HITL) Check
    if (data.requires_approval) {
        const promptText = document.getElementById("approvalPromptText");
        if (promptText && data.approval_request) {
            promptText.textContent = data.approval_request;
        }
        showElement("approvalCard");
        updatePipelineStage("approval");
    } else {
        hideElement("approvalCard");
        updatePipelineStage("approval");
        document.getElementById("step-approval")?.classList.add("completed");
    }

    // 3. Render Trip Context (Constraints + Supervisor Reasoning)
    renderTripContext(data);

    // 4. Render Main Answer and Tabs
    const threadInfoText = document.getElementById("threadInfoText");
    if (threadInfoText) threadInfoText.textContent = `Thread ID: ${data.thread_id}`;

    // Full Plan Tab (Main Answer)
    renderMarkdown(data.answer, document.getElementById("resultBox"));

    // Flight Specialist Tab
    renderMarkdown(data.flight_results, document.getElementById("flightBox"));

    // Hotel Specialist Tab
    renderMarkdown(data.hotel_results, document.getElementById("hotelBox"));

    // Weather Specialist Tab
    renderMarkdown(data.weather_results, document.getElementById("weatherBox"));

    // Budget Specialist Tab
    renderMarkdown(data.budget_results, document.getElementById("budgetBox"));

    showElement("resultSection");

    // Smooth scroll to results or approval card
    const targetElem = data.requires_approval ? document.getElementById("approvalCard") : document.getElementById("resultSection");
    if (targetElem) {
        targetElem.scrollIntoView({ behavior: "smooth", block: "start" });
    }
}

/**
 * Render Trip Constraints tags & Supervisor Reasoning
 */
function renderTripContext(data) {
    const container = document.getElementById("constraintsTags");
    const reasoningBox = document.getElementById("supervisorReasoningText");
    const section = document.getElementById("tripContextSection");

    if (!container || !section) return;
    container.innerHTML = "";

    const constraints = data.trip_constraints || {};
    const selectedAgents = data.selected_agents || [];

    let hasContent = false;

    // Add constraint pills
    if (constraints.destination) {
        container.appendChild(createTag("📍 Destination", constraints.destination));
        hasContent = true;
    }
    if (constraints.origin) {
        container.appendChild(createTag("🛫 Origin", constraints.origin));
        hasContent = true;
    }
    if (constraints.duration) {
        container.appendChild(createTag("⏱️ Duration", constraints.duration));
        hasContent = true;
    }
    if (constraints.budget) {
        container.appendChild(createTag("💵 Budget Limit", constraints.budget));
        hasContent = true;
    }
    if (constraints.travel_style) {
        container.appendChild(createTag("🎨 Style", constraints.travel_style));
        hasContent = true;
    }

    // Add active agent pills
    if (selectedAgents.length > 0) {
        const agentsFormatted = selectedAgents.map(a => a.replace("_agent", "")).join(", ");
        container.appendChild(createTag("🤖 Active Agents", agentsFormatted, "highlight"));
        hasContent = true;
    }

    // Supervisor reasoning text
    if (data.supervisor_reasoning) {
        reasoningBox.textContent = data.supervisor_reasoning;
        hasContent = true;
    }

    if (hasContent) {
        section.classList.remove("hidden");
    } else {
        section.classList.add("hidden");
    }
}

function createTag(label, value, extraClass = "") {
    const span = document.createElement("span");
    span.className = `constraint-tag ${extraClass}`;
    span.innerHTML = `<strong>${label}:</strong> ${value}`;
    return span;
}

/**
 * Toggle Supervisor Reasoning Drawer
 */
function toggleSupervisorReasoning() {
    const box = document.getElementById("supervisorReasoningBox");
    const icon = document.getElementById("reasoningToggleIcon");
    if (!box) return;

    const isHidden = box.classList.contains("hidden");
    if (isHidden) {
        box.classList.remove("hidden");
        icon.textContent = "▲";
    } else {
        box.classList.add("hidden");
        icon.textContent = "▼";
    }
}

/**
 * Switch tabs in result section
 */
function switchTab(tabId, btnElement) {
    const buttons = document.querySelectorAll(".tab-btn");
    const panes = document.querySelectorAll(".tab-pane");

    buttons.forEach(btn => btn.classList.remove("active"));
    panes.forEach(pane => pane.classList.remove("active"));

    if (btnElement) btnElement.classList.add("active");
    const targetPane = document.getElementById(tabId);
    if (targetPane) targetPane.classList.add("active");
}

/**
 * Copy Full Plan to Clipboard
 */
function copyResult() {
    const resultBox = document.getElementById("resultBox");
    const text = resultBox ? resultBox.innerText : "";

    if (!text || text.trim() === "") {
        showToast("No travel plan content to copy.", "error");
        return;
    }

    navigator.clipboard.writeText(text)
        .then(() => showToast("Full travel plan copied to clipboard!", "success"))
        .catch(() => showError("Could not copy text to clipboard."));
}

/**
 * Export Plan to PDF via html2pdf
 */
function downloadPDF() {
    const pdfContent = document.getElementById("pdfContent");

    if (!pdfContent || !pdfContent.innerText.trim()) {
        showToast("No travel plan available to download as PDF.", "error");
        return;
    }

    const downloadBtn = document.querySelector(".download-btn");
    const oldText = downloadBtn ? downloadBtn.innerHTML : "📄 Download PDF";

    if (downloadBtn) {
        downloadBtn.innerHTML = "<span>⏳ Generating PDF...</span>";
        downloadBtn.disabled = true;
    }

    const options = {
        margin: 0.4,
        filename: `TripMate-Travel-Plan-${currentThreadId || "export"}.pdf`,
        image: { type: "jpeg", quality: 0.98 },
        html2canvas: { scale: 2, useCORS: true, backgroundColor: "#ffffff" },
        jsPDF: { unit: "in", format: "a4", orientation: "portrait" },
        pagebreak: { mode: ["avoid-all", "css", "legacy"] }
    };

    html2pdf()
        .set(options)
        .from(pdfContent)
        .save()
        .then(() => {
            showToast("PDF downloaded successfully!", "success");
        })
        .catch((err) => {
            console.error(err);
            showError("Could not generate PDF download.");
        })
        .finally(() => {
            if (downloadBtn) {
                downloadBtn.innerHTML = oldText;
                downloadBtn.disabled = false;
            }
        });
}

// Utility DOM Helpers
function hideElement(id) {
    document.getElementById(id)?.classList.add("hidden");
}

function showElement(id) {
    document.getElementById(id)?.classList.remove("hidden");
}

// Global Keyboard Shortcut (Ctrl + Enter)
document.addEventListener("keydown", function(event) {
    if (event.ctrlKey && event.key === "Enter") {
        const activeElem = document.activeElement;
        if (activeElem && activeElem.id === "feedbackInput") {
            submitApproval(false);
        } else {
            sendMessage();
        }
    }
});