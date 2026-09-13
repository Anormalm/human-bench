"use strict";
// Always load this URL's assignment. Never restore an unrelated workbench packet.
async function loadAssignment() {
  try {
    const response = await fetch("bundle.json", {cache: "no-store"});
    if (!response.ok) throw new Error("Assignment unavailable. Check your assigned link.");
    const packet = await response.json();
    if (!packet.assignment_id) throw new Error("This link has no assigned rater.");
    setBundle(packet);
    $("raterReady").textContent = (bundle.demo ? "SOFTWARE DEMO · Practice answers are synthetic. " : "") +
      bundle.assignment_id + " · " + bundle.items.length + " comparisons · " + answers.length + " saved";
    $("beginAssignment").textContent = answers.length ? "Resume assignment →" : "Begin assignment →";
    $("beginAssignment").disabled = false;
  } catch (e) {
    $("raterReady").textContent = "Assignment could not be opened.";
    error(e.message);
  }
}
$("beginAssignment").onclick = () => {
  $("raterIntro").classList.add("hidden");
  $("raterDesk").classList.remove("hidden");
  startedAt = performance.now();
  window.scrollTo({top: 0, behavior: "smooth"});
};
loadAssignment();
