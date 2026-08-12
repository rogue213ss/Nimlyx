/**
 * Nimlyx homepage -- horizontal row navigation.
 *
 * Lightweight, no dependency. Wraps each `.nimlyx-row` in a
 * `.nimlyx-row-wrap` (markup provided server-side in index.html /
 * feed_row.html) and wires prev/next arrows to smooth-scroll the
 * row by roughly one viewport's worth of cards.
 *
 * Works with lazy-loaded rows too: NimlyxRows.wireAll(root) can be
 * called again after new HTML is injected (e.g. Deals/Action feed
 * rows), and wiring is idempotent per row via a data attribute guard.
 */
(function () {
  "use strict";

  function updateArrowState(wrap) {
    var row = wrap.querySelector(".nimlyx-row");
    var prev = wrap.querySelector(".nimlyx-row-arrow--prev");
    var next = wrap.querySelector(".nimlyx-row-arrow--next");
    if (!row || !prev || !next) return;

    // Nothing to scroll -- content fits within the row's own width.
    // Hide the whole control pair rather than show two dead arrows.
    var canScroll = row.scrollWidth > row.clientWidth + 4;
    wrap.classList.toggle("no-row-scroll", !canScroll);
    if (!canScroll) return;

    var atStart = row.scrollLeft <= 2;
    var atEnd = row.scrollLeft + row.clientWidth >= row.scrollWidth - 2;
    prev.classList.toggle("is-disabled", atStart);
    next.classList.toggle("is-disabled", atEnd);
  }

  function wireRow(wrap) {
    if (wrap.dataset.rowWired === "true") return;
    wrap.dataset.rowWired = "true";

    var row = wrap.querySelector(".nimlyx-row");
    if (!row) return;

    updateArrowState(wrap);
    row.addEventListener("scroll", function () { updateArrowState(wrap); }, { passive: true });
    window.addEventListener("resize", function () { updateArrowState(wrap); });
  }

  function scrollRow(wrap, direction) {
    var row = wrap.querySelector(".nimlyx-row");
    if (!row) return;
    var amount = Math.max(row.clientWidth * 0.85, 240);
    row.scrollBy({ left: direction * amount, behavior: "smooth" });
  }

  // Delegated click listener -- covers arrows added after initial
  // load (lazy-loaded Deals/Action rows) without re-binding per row.
  document.addEventListener("click", function (e) {
    var btn = e.target.closest(".nimlyx-row-arrow");
    if (!btn || btn.classList.contains("is-disabled")) return;
    var wrap = btn.closest(".nimlyx-row-wrap");
    if (!wrap) return;
    scrollRow(wrap, btn.classList.contains("nimlyx-row-arrow--prev") ? -1 : 1);
  });

  function wireAll(root) {
    var scope = root || document;
    var wraps = scope.querySelectorAll(".nimlyx-row-wrap");
    for (var i = 0; i < wraps.length; i++) wireRow(wraps[i]);
  }

  window.NimlyxRows = { wireAll: wireAll };
  document.addEventListener("DOMContentLoaded", function () { wireAll(document); });

  /**
   * Image fallback chain for card artwork.
   *
   * No single Steam CDN URL is actually guaranteed to exist for
   * every app_id (confirmed live -- a recent app_id 404'd even on
   * the "classic" header.jpg path). Rather than trust one guess,
   * this walks through every candidate in data-img-candidates on
   * each load failure, and only once all of them have failed does
   * it give up -- hiding the <img> so the CSS placeholder in
   * .nimlyx-card-media (a neutral glyph on the elevated background)
   * shows instead of the browser's broken-image icon.
   *
   * Wired via an inline onerror="" attribute in the template rather
   * than a JS query, so it works automatically on lazy-loaded
   * Deals/Action content too -- no separate re-wiring call needed.
   */
  window.NimlyxImgFallback = function (img) {
    if (img.dataset.fallbackDone === "true") return;

    var candidates = [];
    try { candidates = JSON.parse(img.dataset.imgCandidates || "[]"); } catch (e) { candidates = []; }

    var tried = parseInt(img.dataset.fallbackIndex || "0", 10);
    if (tried < candidates.length) {
      img.dataset.fallbackIndex = String(tried + 1);
      img.src = candidates[tried]; // onerror fires again naturally if this one also 404s
      return;
    }

    img.dataset.fallbackDone = "true";
    img.dataset.broken = "true";
    img.removeAttribute("src");
  };
})();
