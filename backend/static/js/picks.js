/* ==========================================================
   NIMLYX PICKS — master-detail interaction

   Clicking a card in the right-hand feed does NOT navigate. It
   swaps the large panel on the left (image, badge, title, insight,
   why-it-matters) to show that pick instead, and updates the left
   panel's "Read Full Analysis" button to point at that game. Only
   that button actually navigates anywhere — verdict cards
   themselves are pure browsing, no accidental page leaves.

   All data needed for the swap is already server-rendered onto
   each feed button's data-* attributes, so this needs no fetch —
   just reading dataset and writing it into the lead panel.
========================================================== */

(function () {
    const feed = document.getElementById("picksFeed");
    if (!feed) return;

    const lead = document.getElementById("picksLead");
    const leadMedia = document.getElementById("picksLeadMedia");
    const leadBadge = document.getElementById("picksLeadBadge");
    const leadTitle = document.getElementById("picksLeadTitle");
    const leadInsight = document.getElementById("picksLeadInsight");
    const leadWhy = document.getElementById("picksLeadWhy");
    const leadCta = document.getElementById("picksLeadCta");

    const BADGE_CLASSES = ["badge-worth", "badge-hidden", "badge-fresh", "badge-critic", "badge-split", "badge-fallback"];

    feed.addEventListener("click", (event) => {
        const card = event.target.closest(".pick-card");
        if (!card) return;

        const { name, image, candidates, insight, why, url, badgeClass, badgeIcon, badgeLabel } = card.dataset;

        if (leadMedia) {
            // Guaranteed image first, immediately — same rule as every
            // other card. Candidates are only ever swapped in after a
            // real, successful load; see image-upgrade.js.
            leadMedia.style.backgroundImage = `url('${image}')`;
            leadMedia.dataset.bgCandidates = candidates || "[]";
            if (window.NimlyxImageUpgrade) {
                window.NimlyxImageUpgrade.upgradeBackground(leadMedia, candidates);
            }
        }
        if (leadTitle) leadTitle.textContent = name || "";
        if (leadInsight) leadInsight.textContent = insight || "";
        if (leadWhy) leadWhy.textContent = why || "";
        if (leadCta) leadCta.href = url || "#";

        if (leadBadge) {
            leadBadge.textContent = `${badgeIcon || ""} ${badgeLabel || ""}`.trim();
            leadBadge.className = `pick-badge ${badgeClass || ""}`.trim();
        }

        if (lead) {
            lead.classList.remove(...BADGE_CLASSES);
            if (badgeClass) lead.classList.add(badgeClass);
        }

        feed.querySelectorAll(".pick-card").forEach((c) => c.classList.remove("is-active"));
        card.classList.add("is-active");
    });
})();