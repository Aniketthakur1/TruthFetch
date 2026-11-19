const form = document.getElementById("check-form");
const input = document.getElementById("claim");
const count = document.getElementById("char-count");
const button = document.getElementById("submit-btn");
const result = document.getElementById("result");

input.addEventListener("input", () => count.textContent = `${input.value.length} / 4000`);
document.getElementById("clear-btn").addEventListener("click", () => {
  input.value = ""; count.textContent = "0 / 4000"; input.focus();
});
document.querySelectorAll(".example").forEach(el => el.addEventListener("click", () => {
  input.value = el.textContent.replace(/[“”]/g, "").trim();
  count.textContent = `${input.value.length} / 4000`;
  input.focus();
}));

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}
function renderItems(items, type) {
  if (!items || !items.length) return `<div class="empty-state">No matching ${type} were returned. This does not prove the claim is false.</div>`;
  return items.map(item => {
    if (type === "fact-check reviews") {
      return `<article class="evidence-item"><div class="evidence-meta">${escapeHtml(item.publisher)}${item.date ? " · " + escapeHtml(item.date) : ""}</div><h4>${escapeHtml(item.title)}</h4><p>Publisher rating: <b>${escapeHtml(item.rating)}</b></p>${item.url ? `<a href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">Read original review ↗</a>` : ""}</article>`;
    }
    return `<article class="evidence-item"><div class="evidence-meta">${escapeHtml(item.domain || "Web source")}${item.published_date ? " · " + escapeHtml(item.published_date) : ""}</div><h4>${escapeHtml(item.title)}</h4><p>${escapeHtml(item.snippet || "")}</p>${item.url ? `<a href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">Open source ↗</a>` : ""}</article>`;
  }).join("");
}
form.addEventListener("submit", async event => {
  event.preventDefault();
  const claim = input.value.trim();
  if (claim.length < 12) { alert("Please enter a claim with at least 12 characters."); return; }
  button.disabled = true; button.innerHTML = "Researching sources… <span>⌛</span>";
  try {
    const response = await fetch("/api/check", {
      method: "POST", headers: {"Content-Type":"application/json"},
      body: JSON.stringify({claim})
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "The check could not be completed.");
    document.getElementById("verdict").textContent = data.verdict;
    document.getElementById("explanation").textContent = data.explanation;
    document.getElementById("confidence").textContent = data.confidence;
    document.getElementById("claim-output").textContent = data.claim;
    document.getElementById("fact-checks").innerHTML = renderItems(data.fact_checks, "fact-check reviews");
    document.getElementById("sources").innerHTML = renderItems(data.sources, "web sources");
    document.getElementById("disclaimer").textContent = data.disclaimer;
    document.getElementById("coverage").innerHTML =
      `<span class="coverage-chip"><b>${data.coverage.google_fact_check_api ? "●" : "○"}</b> Fact-check database ${data.coverage.google_fact_check_api ? "connected" : "not configured"}</span>` +
      `<span class="coverage-chip"><b>${data.coverage.live_web_search ? "●" : "○"}</b> Live web search ${data.coverage.live_web_search ? "connected" : "not configured"}</span>`;
    const icon = document.getElementById("verdict-icon");
    icon.textContent = data.verdict.toLowerCase().includes("false") ? "!" : data.verdict.toLowerCase().includes("supported") ? "✓" : "?";
    result.classList.remove("hidden");
    result.scrollIntoView({behavior:"smooth", block:"start"});
  } catch (error) {
    alert(error.message);
  } finally {
    button.disabled = false; button.innerHTML = 'Investigate claim <span>→</span>';
  }
});
