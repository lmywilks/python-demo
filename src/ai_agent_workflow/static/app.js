const workflowList = document.querySelector("#workflow-list");
const result = document.querySelector("#result");
const status = document.querySelector("#status");
const taskInput = document.querySelector("#task");
const clearResult = document.querySelector("#clear-result");
const MOCK_STEP_DELAY_MS = 500;
let activeRunId = 0;
let currentPausedState = null;
let currentCompletedState = null;
let currentTimeline = null;

function setStatus(text) {
  status.textContent = text;
}

function renderTextResult(text, isError = false) {
  result.className = `result-body${isError ? " error" : ""}`;
  result.textContent = text;
}

function sleep(ms) {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

function renderPendingWorkflow(workflow) {
  result.className = "result-body";
  result.replaceChildren();

  const timelineTitle = document.createElement("h3");
  timelineTitle.textContent = "LangGraph Process";

  const timeline = document.createElement("ol");
  timeline.className = "process-list";
  timeline.append(createProcessItem({
    node: workflow.id,
    status: "running",
    message: "Starting workflow...",
  }));

  result.append(timelineTitle, timeline);
}

function createProcessItem(event) {
  const item = document.createElement("li");
  item.className = `process-item process-${event.status || "completed"}`;

  const node = document.createElement("strong");
  node.textContent = event.node;

  const statusText = document.createElement("span");
  statusText.textContent = event.status || "completed";

  if (event.status === "running" || event.status === "pending") {
    const spinner = document.createElement("i");
    spinner.className = "loader";
    spinner.setAttribute("aria-hidden", "true");
    statusText.prepend(spinner);
  }

  const message = document.createElement("p");
  message.textContent = event.message || "";

  item.append(node, statusText, message);
  return item;
}

function renderSummary(data) {
  const state = data.state || {};
  const summary = document.createElement("dl");
  summary.className = "summary-grid";
  [
    ["Status", data.status || "unknown"],
    ["Workflow", data.workflow_id],
    ["Public response", data.public_message || "not set"],
    ["Request ID", state.request_id || "not set"],
    ["Email", state.email || "not provided"],
    ["Audit events", String((state.audit_log || []).length)],
  ].forEach(([label, value]) => {
    const term = document.createElement("dt");
    term.textContent = label;
    const description = document.createElement("dd");
    description.textContent = value;
    summary.append(term, description);
  });
  return summary;
}

function appendHumanInputForm(data, workflow) {
  const panel = document.createElement("section");
  panel.className = "human-panel";

  const formTitle = document.createElement("h3");
  formTitle.textContent = "Human Verification";

  const form = document.createElement("form");
  form.className = "human-form";

  const prompt = document.createElement("p");
  prompt.textContent = data.state?.human_prompt || "Enter verification details to continue.";

  const codeLabel = document.createElement("label");
  codeLabel.textContent = "MFA code";
  codeLabel.htmlFor = "human-mfa-code";
  const codeInput = document.createElement("input");
  codeInput.id = "human-mfa-code";
  codeInput.name = "mfa_code";
  codeInput.placeholder = "123456";
  codeInput.autocomplete = "one-time-code";
  codeInput.inputMode = "numeric";
  codeInput.required = true;

  const passwordLabel = document.createElement("label");
  passwordLabel.textContent = "New password";
  passwordLabel.htmlFor = "human-new-password";
  const passwordInput = document.createElement("input");
  passwordInput.id = "human-new-password";
  passwordInput.name = "new_password";
  passwordInput.type = "password";
  passwordInput.placeholder = "Str0ngTestPass!";
  passwordInput.autocomplete = "new-password";
  passwordInput.minLength = 12;
  passwordInput.pattern = "(?=.*\\d).{12,}";
  passwordInput.required = true;
  passwordInput.title = "Use at least 12 characters and include at least one number.";
  passwordInput.setAttribute("aria-describedby", "password-format-hint");

  const passwordHint = document.createElement("p");
  passwordHint.id = "password-format-hint";
  passwordHint.className = "field-hint";
  passwordHint.textContent = "Use at least 12 characters and include at least one number.";

  const submit = document.createElement("button");
  submit.className = "start-button";
  submit.type = "submit";
  submit.textContent = "Continue Workflow";

  form.append(prompt, codeLabel, codeInput, passwordLabel, passwordInput, passwordHint, submit);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    await resumeWorkflow(workflow, submit, {
      mfa_code: codeInput.value.trim(),
      new_password: passwordInput.value,
    });
  });

  panel.append(formTitle, form);
  result.append(panel);
}

function appendPasswordVerificationPanel(data, workflow) {
  if (data.status !== "completed" || !data.state?.password_reset) {
    return;
  }
  currentCompletedState = data.state;

  const panel = document.createElement("section");
  panel.className = "verify-panel";

  const title = document.createElement("h3");
  title.textContent = "Verify Password Update";

  const form = document.createElement("form");
  form.className = "human-form";

  const label = document.createElement("label");
  label.textContent = "Updated password";
  label.htmlFor = "verify-password";

  const input = document.createElement("input");
  input.id = "verify-password";
  input.name = "password";
  input.type = "password";
  input.autocomplete = "current-password";
  input.required = true;

  const submit = document.createElement("button");
  submit.className = "start-button";
  submit.type = "submit";
  submit.textContent = "Verify";

  const message = document.createElement("p");
  message.className = "verify-message";
  message.setAttribute("aria-live", "polite");

  form.append(label, input, submit, message);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    await verifyPasswordUpdate(workflow, input.value, submit, message);
  });

  panel.append(title, form);
  result.append(panel);
}

function appendFinalAnswer(data, workflow) {
  if (!data.final_answer) {
    return;
  }
  const finalTitle = document.createElement("h3");
  finalTitle.textContent = "Final Answer";
  const finalAnswer = document.createElement("pre");
  finalAnswer.textContent = data.final_answer;
  result.append(finalTitle, finalAnswer);
  appendPasswordVerificationPanel(data, workflow);
}

async function renderWorkflowResult(data, runId, workflow) {
  const process = data.process || [];
  currentPausedState = null;
  currentTimeline = null;
  result.className = "result-body";
  result.replaceChildren(renderSummary(data));

  if (runId !== activeRunId) {
    return;
  }
  const timelineTitle = document.createElement("h3");
  timelineTitle.textContent = "LangGraph Process";

  const timeline = document.createElement("ol");
  timeline.className = "process-list";
  currentTimeline = timeline;
  result.append(timelineTitle, timeline);

  for (const [index, event] of process.entries()) {
    if (runId !== activeRunId) {
      return;
    }
    const runningEvent = {
      node: event.node,
      status: "running",
      message: `Running ${event.node}...`,
    };
    timeline.append(createProcessItem(runningEvent));
    setStatus(`Step ${index + 1}/${process.length}`);
    await sleep(MOCK_STEP_DELAY_MS);

    if (runId !== activeRunId) {
      return;
    }
    timeline.replaceChild(createProcessItem(event), timeline.lastElementChild);
    await sleep(MOCK_STEP_DELAY_MS);
  }

  appendFinalAnswer(data, workflow);

  if (data.status === "needs_input" && runId === activeRunId) {
    currentPausedState = data.state || null;
    appendHumanInputForm(data, workflow);
  }
}

async function renderResumeResult(data, runId) {
  const process = data.process || [];
  const timeline = currentTimeline;
  const humanPanel = result.querySelector(".human-panel");
  if (humanPanel) {
    humanPanel.remove();
  }

  const summary = result.querySelector(".summary-grid");
  if (summary) {
    summary.replaceWith(renderSummary(data));
  }

  if (!timeline) {
    await renderWorkflowResult(data, runId, { steps: [] });
    return;
  }

  for (const [index, event] of process.entries()) {
    if (runId !== activeRunId) {
      return;
    }

    const runningEvent = {
      node: event.node,
      status: "running",
      message: `Running ${event.node}...`,
    };
    const replacesWaitingHumanStep =
      index === 0 &&
      event.node === "collect_human_verification" &&
      timeline.lastElementChild?.querySelector("strong")?.textContent === "collect_human_verification";

    if (replacesWaitingHumanStep) {
      timeline.replaceChild(createProcessItem(runningEvent), timeline.lastElementChild);
    } else {
      timeline.append(createProcessItem(runningEvent));
    }

    setStatus(`Continuing ${index + 1}/${process.length}`);
    await sleep(MOCK_STEP_DELAY_MS);

    if (runId !== activeRunId) {
      return;
    }
    timeline.replaceChild(createProcessItem(event), timeline.lastElementChild);
    await sleep(MOCK_STEP_DELAY_MS);
  }

  appendFinalAnswer(data, { id: data.workflow_id });
}

async function verifyPasswordUpdate(workflow, password, button, message) {
  if (!currentCompletedState) {
    message.className = "verify-message verify-error";
    message.textContent = "No completed workflow is available to verify.";
    return;
  }

  const originalButtonText = button.textContent;
  button.disabled = true;
  button.textContent = "Verifying";
  message.className = "verify-message";
  message.textContent = "";

  try {
    const response = await fetch(`/api/workflows/${workflow.id}/verify-password`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ state: currentCompletedState, password }),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || `Verification failed: ${response.status}`);
    }
    message.className = `verify-message ${data.verified ? "verify-success" : "verify-error"}`;
    message.textContent = data.message;
    if (data.verified) {
      const panel = button.closest(".verify-panel");
      const input = panel?.querySelector("#verify-password");
      const label = panel?.querySelector('label[for="verify-password"]');
      button.remove();
      input?.remove();
      label?.remove();
      return;
    }
    button.textContent = data.verified ? "Verified" : "Retry";
    button.disabled = data.verified;
  } catch (error) {
    message.className = "verify-message verify-error";
    message.textContent = error.message;
    button.textContent = "Retry";
    button.disabled = false;
  } finally {
    if (!button.disabled && button.textContent !== "Retry") {
      button.textContent = originalButtonText;
    }
  }
}

function workflowCard(workflow) {
  const card = document.createElement("article");
  card.className = "workflow-card";

  const details = document.createElement("div");
  const title = document.createElement("h3");
  title.textContent = workflow.name;

  const description = document.createElement("p");
  description.textContent = workflow.description;

  const steps = document.createElement("ul");
  steps.className = "steps";
  workflow.steps.forEach((step) => {
    const item = document.createElement("li");
    item.textContent = step;
    steps.append(item);
  });

  details.append(title, description, steps);

  const button = document.createElement("button");
  button.className = "start-button";
  button.type = "button";
  button.textContent = "Start Workflow";
  button.addEventListener("click", () => startWorkflow(workflow, button));

  card.append(details, button);
  return card;
}

async function loadWorkflows() {
  setStatus("Loading");
  try {
    const response = await fetch("/api/workflows");
    if (!response.ok) {
      throw new Error(`Failed to load workflows: ${response.status}`);
    }
    const data = await response.json();
    workflowList.replaceChildren(...data.workflows.map(workflowCard));
    setStatus(`${data.workflows.length} ready`);
  } catch (error) {
    setStatus("Error");
    renderTextResult(error.message, true);
  }
}

async function startWorkflow(workflow, button, humanInputs = {}) {
  const task = taskInput.value.trim();
  if (!task) {
    taskInput.focus();
    renderTextResult("Enter a task before starting a workflow.", true);
    return;
  }

  const runId = activeRunId + 1;
  activeRunId = runId;
  currentPausedState = null;
  currentCompletedState = null;
  const originalButtonText = button.textContent;
  button.disabled = true;
  button.textContent = "Running";
  setStatus("Running");
  renderPendingWorkflow(workflow);

  try {
    const response = await fetch(`/api/workflows/${workflow.id}/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task, human_inputs: humanInputs }),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || `Workflow failed: ${response.status}`);
    }
    await renderWorkflowResult(data, runId, workflow);
    if (runId === activeRunId) {
      setStatus(data.status === "needs_input" ? "Needs input" : "Complete");
    }
  } catch (error) {
    renderTextResult(error.message, true);
    setStatus("Error");
  } finally {
    button.disabled = false;
    button.textContent = originalButtonText;
  }
}

async function resumeWorkflow(workflow, button, humanInputs = {}) {
  if (!currentPausedState) {
    renderTextResult("No paused workflow state is available to resume.", true);
    return;
  }

  const runId = activeRunId + 1;
  activeRunId = runId;
  const originalButtonText = button.textContent;
  button.disabled = true;
  button.textContent = "Continuing";
  setStatus("Continuing");

  try {
    const response = await fetch(`/api/workflows/${workflow.id}/resume`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ state: currentPausedState, human_inputs: humanInputs }),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || `Workflow failed: ${response.status}`);
    }
    currentPausedState = null;
    currentCompletedState = null;
    await renderResumeResult(data, runId);
    if (runId === activeRunId) {
      setStatus(data.status === "needs_input" ? "Needs input" : "Complete");
    }
  } catch (error) {
    renderTextResult(error.message, true);
    setStatus("Error");
  } finally {
    button.disabled = false;
    button.textContent = originalButtonText;
  }
}

clearResult.addEventListener("click", () => {
  activeRunId += 1;
  currentPausedState = null;
  currentCompletedState = null;
  currentTimeline = null;
  renderTextResult("Choose a workflow and start it.");
  setStatus("Ready");
});

loadWorkflows();
