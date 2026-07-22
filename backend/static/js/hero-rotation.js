/* ==========================================================
   HOMEPAGE HERO — auto-rotating carousel
   Slides are already server-rendered by Jinja (featured_games),
   each holding data-name / data-description / data-analyze-url.
   This just cycles which one is visible + updates the text.
========================================================== */

(function () {
    const ROTATE_MS = 3500;
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const heroSection = document.getElementById("homeHero");
    if (!heroSection) return;

    const slides = Array.from(heroSection.querySelectorAll(".home-hero-slide"));
    const dots = Array.from(document.querySelectorAll(".home-hero-dot"));
    const titleEl = document.getElementById("homeHeroTitle");
    const descEl = document.getElementById("homeHeroDesc");
    const ctaEl = document.getElementById("homeHeroCta");

    if (slides.length <= 1) return;

    let currentIndex = 0;
    let rotateTimer = null;

    function goToSlide(index) {
        slides.forEach((slide, i) => slide.classList.toggle("is-active", i === index));
        dots.forEach((dot, i) => dot.classList.toggle("is-active", i === index));

        const slide = slides[index];
        if (titleEl) titleEl.textContent = slide.dataset.name || "";
        if (descEl) descEl.textContent = slide.dataset.description || "";
        if (ctaEl) ctaEl.href = slide.dataset.analyzeUrl || "#";

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