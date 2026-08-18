/* ==========================================================
   HOMEPAGE HERO — auto-rotating carousel
   Slides are server-rendered by Jinja (featured_games), each
   holding data-name / data-analyze-url / data-steam-url /
   data-badge-icon / data-genres / data-discount / data-review-desc /
   data-insight. This cycles which slide is visible and keeps the
   left-column content (title, description, meta chips, buttons) in
   sync with whichever slide is currently showing.
========================================================== */

(function () {
    const ROTATE_MS = 6000;
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const heroSection = document.getElementById("homeHero");
    if (!heroSection) return;

    const slides = Array.from(heroSection.querySelectorAll(".home-hero-slide"));
    const dots = Array.from(document.querySelectorAll(".home-hero-dot"));
    const prevBtn = document.getElementById("homeHeroPrev");
    const nextBtn = document.getElementById("homeHeroNext");

    const titleEl = document.getElementById("homeHeroTitle");
    const descEl = document.getElementById("homeHeroDesc");
    const metaEl = document.getElementById("homeHeroMeta");
    const ctaEl = document.getElementById("homeHeroCta");
    const steamCtaEl = document.getElementById("homeHeroSteamCta");

    if (slides.length <= 1) return;

    let currentIndex = 0;
    let rotateTimer = null;

    function renderMeta(slide) {
        if (!metaEl) return;
        metaEl.innerHTML = "";

        // Review pill first, matching the server-rendered order for g0
        // (see templates/index.html) so slide 1 and later slides look
        // identical, not just similarly styled.
        const reviewDesc = slide.dataset.reviewDesc;
        if (reviewDesc) {
            const sentiment = slide.dataset.reviewSentiment || "neutral";
            const pill = document.createElement("span");
            pill.className = `home-hero-pill home-hero-pill--review is-${sentiment}`;

            const icon = document.createElement("span");
            icon.setAttribute("aria-hidden", "true");
            icon.textContent = sentiment === "positive" ? "👍" : sentiment === "negative" ? "👎" : "◐";
            pill.appendChild(icon);
            pill.appendChild(document.createTextNode(" " + reviewDesc));
            metaEl.appendChild(pill);
        }

        let genres = [];
        try {
            genres = JSON.parse(slide.dataset.genres || "[]");
        } catch (e) {
            genres = [];
        }
        genres.forEach((genre) => {
            const pill = document.createElement("span");
            pill.className = "home-hero-pill hero-meta-genre";
            pill.textContent = genre;
            metaEl.appendChild(pill);
        });

        const discount = parseInt(slide.dataset.discount, 10) || 0;
        if (discount > 0) {
            const pill = document.createElement("span");
            pill.className = "home-hero-pill home-hero-pill--discount";

            const off = document.createElement("span");
            off.className = "home-hero-pill-off";
            off.textContent = `-${discount}%`;
            pill.appendChild(off);

            const price = slide.dataset.price;
            if (price) {
                const priceEl = document.createElement("span");
                priceEl.className = "home-hero-pill-price";
                priceEl.textContent = price;
                pill.appendChild(priceEl);
            }

            const priceBefore = slide.dataset.priceBefore;
            if (priceBefore) {
                const wasEl = document.createElement("span");
                wasEl.className = "home-hero-pill-price-was";
                wasEl.textContent = priceBefore;
                pill.appendChild(wasEl);
            }

            metaEl.appendChild(pill);
        }
    }

    function goToSlide(index) {
        slides.forEach((slide, i) => slide.classList.toggle("is-active", i === index));
        dots.forEach((dot, i) => dot.classList.toggle("is-active", i === index));

        const slide = slides[index];
        if (titleEl) titleEl.textContent = slide.dataset.name || "";
        if (descEl) {
            const insight = slide.dataset.insight || "";
            descEl.textContent = insight;
            descEl.style.display = insight ? "" : "none";
        }
        if (ctaEl) ctaEl.href = slide.dataset.analyzeUrl || "#";
        if (steamCtaEl) steamCtaEl.href = slide.dataset.steamUrl || "#";
        renderMeta(slide);

        currentIndex = index;
    }

    function nextSlide() {
        goToSlide((currentIndex + 1) % slides.length);
    }

    function prevSlide() {
        goToSlide((currentIndex - 1 + slides.length) % slides.length);
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

    if (prevBtn) {
        prevBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            prevSlide();
            restartRotation();
        });
    }
    if (nextBtn) {
        nextBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            nextSlide();
            restartRotation();
        });
    }

    startRotation();
})();
