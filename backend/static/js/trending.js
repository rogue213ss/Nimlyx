/* ==========================================================
   TRENDING TODAY — arrow-driven horizontal scroll

   Replaces the raw native scrollbar with two circular arrow
   buttons. Each click scrolls by roughly one card's width; arrows
   fade out (rather than just disabling) when there's nothing left
   in that direction, so the control itself communicates state
   instead of needing a separate scrollbar affordance.
========================================================== */

(function () {
    const scroller = document.getElementById("trendingScroll");
    const prevBtn = document.getElementById("trendingPrev");
    const nextBtn = document.getElementById("trendingNext");
    if (!scroller || !prevBtn || !nextBtn) return;

    function scrollStep() {
        const card = scroller.querySelector(".trending-card");
        const cardWidth = card ? card.getBoundingClientRect().width : 340;
        return cardWidth + 18; // card width + gap
    }

    function updateArrowState() {
        const maxScroll = scroller.scrollWidth - scroller.clientWidth;
        prevBtn.disabled = scroller.scrollLeft <= 4;
        nextBtn.disabled = scroller.scrollLeft >= maxScroll - 4;
    }

    prevBtn.addEventListener("click", () => {
        scroller.scrollBy({ left: -scrollStep(), behavior: "smooth" });
    });

    nextBtn.addEventListener("click", () => {
        scroller.scrollBy({ left: scrollStep(), behavior: "smooth" });
    });

    scroller.addEventListener("scroll", updateArrowState, { passive: true });
    window.addEventListener("resize", updateArrowState);

    updateArrowState();
})();
