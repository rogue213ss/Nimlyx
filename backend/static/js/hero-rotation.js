/* ==========================================================
   HOMEPAGE HERO — auto-rotating carousel
   Slides are server-rendered by Jinja (featured_games), each
   holding data-name / data-analyze-url / data-insight / data-why.
   This cycles which one is visible, updates the title + CTA, and
   keeps the separate "Nimlyx Insight" callout bar below the hero
   in sync with whichever game is currently showing.
========================================================== */

(function () {
    const ROTATE_MS = 4000;
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const heroSection = document.getElementById("homeHero");
    if (!heroSection) return;

    const slides = Array.from(heroSection.querySelectorAll(".home-hero-slide"));
    const dots = Array.from(document.querySelectorAll(".home-hero-dot"));
    const titleEl = document.getElementById("homeHeroTitle");
    const ctaEl = document.getElementById("homeHeroCta");
    const insightHeadlineEl = document.getElementById("homeInsightHeadline");
    const insightWhyEl = document.getElementById("homeInsightWhy");

    if (slides.length <= 1) return;

    let currentIndex = 0;
    let rotateTimer = null;

    function goToSlide(index) {
        slides.forEach((slide, i) => slide.classList.toggle("is-active", i === index));
        dots.forEach((dot, i) => dot.classList.toggle("is-active", i === index));

        const slide = slides[index];
        if (titleEl) titleEl.textContent = slide.dataset.name || "";
        if (ctaEl) ctaEl.href = slide.dataset.analyzeUrl || "#";
        if (insightHeadlineEl) insightHeadlineEl.textContent = slide.dataset.insight || "";
        if (insightWhyEl) insightWhyEl.textContent = slide.dataset.why || "";

        currentIndex = index;
    }

    function nextSlide() {
        goToSlide((currentIndex + 1) % slides.length);
    }

    function startRotation() {
        if (reduceMotion) return;
        rotateTimer = setInterval(nextSlide, ROTATE_MS);
    }

    function restartRotation() {
        clearInterval(rotateTimer);
        startRotation();
    }

    dots.forEach((dot, i) => {
        dot.addEventListener("click", (e) => {
            e.stopPropagation();
            goToSlide(i);
            restartRotation();
        });
    });

    startRotation();
})();