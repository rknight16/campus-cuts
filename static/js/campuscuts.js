// Submit feedback: one submit per form, and a "Saving…" state on the button while the page loads.
document.addEventListener("submit", (event) => {
  const form = event.target;
  if (form.dataset.submitting) { event.preventDefault(); return; }
  form.dataset.submitting = "1";
  const button = event.submitter || form.querySelector("button");
  if (!button || !button.classList.contains("btn") || form.method !== "post") return;
  const label = [...button.childNodes].reverse().find((n) => n.nodeType === Node.TEXT_NODE && n.textContent.trim());
  if (label) { button.dataset.label = label.textContent; label.textContent = button.dataset.busyLabel || "Saving…"; }
  button.setAttribute("aria-busy", "true");
  button.setAttribute("aria-disabled", "true");
});

// Coming back with the Back button restores the page from cache: undo the busy state.
window.addEventListener("pageshow", (event) => {
  if (!event.persisted) return;
  document.querySelectorAll("form[data-submitting]").forEach((form) => delete form.dataset.submitting);
  document.querySelectorAll(".btn[aria-busy]").forEach((button) => {
    const label = [...button.childNodes].reverse().find((n) => n.nodeType === Node.TEXT_NODE && n.textContent.trim());
    if (label && button.dataset.label) label.textContent = button.dataset.label;
    button.removeAttribute("aria-busy");
    button.removeAttribute("aria-disabled");
  });
});

// Handoff amounts: before saving, say how the typed amount compares with what the system expects.
const money = (n) => "$" + n.toLocaleString("en-US", { minimumFractionDigits: n % 1 ? 2 : 0, maximumFractionDigits: 2 });

function showDiff(input) {
  const out = document.getElementById(input.dataset.diffId);
  if (!out) return;
  const expected = parseFloat(input.dataset.expected);
  const typed = parseFloat(input.value);
  out.dataset.state = "";
  if (Number.isNaN(expected) || Number.isNaN(typed)) { out.textContent = ""; return; }
  const gap = Math.round((typed - expected) * 100) / 100;
  const noun = input.dataset.compareNoun;
  if (gap === 0) { out.textContent = `Matches the ${money(expected)} ${noun}.`; return; }
  out.dataset.state = "warn";
  out.textContent = `${money(Math.abs(gap))} ${gap < 0 ? "less" : "more"} than the ${money(expected)} ${noun}.` +
    (input.dataset.flag ? " It will be flagged as a mismatch." : "");
}

document.querySelectorAll("input[data-diff-id]").forEach((input) => {
  input.addEventListener("input", () => { input.dataset.touched = "1"; showDiff(input); });
  showDiff(input);
});

// Changing the rent period updates the expected amount, and the amount itself until you type your own.
document.querySelectorAll("form[data-handoff-form] select[name=period]").forEach((select) => {
  const amount = select.form.elements.amount;
  const note = select.form.querySelector("[data-expected-note]");
  select.addEventListener("change", () => {
    const raw = select.selectedOptions[0] && select.selectedOptions[0].dataset.expected;
    if (raw === undefined) {
      note.hidden = true;
      delete amount.dataset.expected;
    } else {
      const expected = parseFloat(raw);
      note.hidden = false;
      note.querySelector("[data-expected-amount]").textContent = money(expected);
      amount.dataset.expected = raw;
      if (!amount.dataset.touched) amount.value = expected > 0 ? String(expected) : "";
    }
    showDiff(amount);
  });
});
