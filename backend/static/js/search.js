/* ==========================================================
   REGION / CURRENCY PICKER
   Auto-detected via IP on the backend; this lets the user override
   it. "Auto" always maps back to whatever the backend detects.
========================================================== */

async function initRegionPicker() {
    const picker = document.getElementById("regionPicker");
    const trigger = document.getElementById("regionTrigger");
    const triggerLabel = document.getElementById("regionTriggerLabel");
    const menu = document.getElementById("regionMenu");
    if (!picker || !trigger || !menu) return;

    let currentValue = "auto";

    async function applyChoice(choice) {
        try {
            if (choice === "auto") {
                await fetch("/api/region/reset", { method: "POST" });
            } else {
                await fetch(`/api/region/${choice}`, { method: "POST" });
            }
            location.reload();
        } catch (error) {
            console.error("Error setting region:", error);
        }
    }

    function renderMenu(data) {
        currentValue = data.is_manual ? data.active : "auto";

        const autoItem = {
            value: "auto",
            label: `Auto-detect (${data.detected})`
        };
        const items = [autoItem, ...(data.options || [])];

        menu.innerHTML = items.map((opt, i) => `
            ${i === 1 ? '<div class="region-picker__divider"></div>' : ""}
            <div class="region-picker__item ${opt.value === currentValue || opt.code === currentValue ? "is-active" : ""}"
                 role="option" data-value="${opt.value || opt.code}">
                ${opt.label}
            </div>
        `).join("");

        const activeItem = items.find(o => (o.value || o.code) === currentValue);
        triggerLabel.textContent = activeItem ? activeItem.label : "Region";

        menu.querySelectorAll(".region-picker__item").forEach(item => {
            item.addEventListener("click", () => {
                closeMenu();
                applyChoice(item.dataset.value);
            });
        });
    }

    function openMenu() {
        picker.classList.add("is-open");
        trigger.setAttribute("aria-expanded", "true");
    }
    function closeMenu() {
        picker.classList.remove("is-open");
        trigger.setAttribute("aria-expanded", "false");
    }

    trigger.addEventListener("click", (e) => {
        e.stopPropagation();
        picker.classList.contains("is-open") ? closeMenu() : openMenu();
    });
    document.addEventListener("click", (e) => {
        if (!picker.contains(e.target)) closeMenu();
    });
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") closeMenu();
    });

    try {
        const res = await fetch("/api/region");
        const data = await res.json();
        renderMenu(data);
    } catch (error) {
        console.error("Error loading region options:", error);
        triggerLabel.textContent = "Region";
    }
}

initRegionPicker();

/* ==========================================================
   SEARCH BAR + SUGGESTIONS (reused Nimlyx logic)
========================================================== */

function searchGame(name) {
    window.location.href = `/search?q=${encodeURIComponent(name)}`;
}

document.getElementById("searchBtn").addEventListener("click", () => {
    const gameName = document.getElementById("gameInput").value.trim();
    if (!gameName) return;
    searchGame(gameName);
});

let debounceTimer;
let activeSuggestionIndex = -1;

document.getElementById("gameInput").addEventListener("input", (e) => {
    clearTimeout(debounceTimer);
    const query = e.target.value;

    if (query.length < 2) {
        document.getElementById("suggestions").innerHTML = "";
        return;
    }

    debounceTimer = setTimeout(() => {
        fetchSuggestions(query);
    }, 400);
});

document.getElementById("gameInput").addEventListener("keydown", (e) => {
    const suggestionsBox = document.getElementById("suggestions");
    const items = suggestionsBox.querySelectorAll(".suggestion-item");

    if (items.length === 0) {
        if (e.key === "Enter") document.getElementById("searchBtn").click();
        return;
    }

    if (e.key === "ArrowDown") {
        e.preventDefault();
        activeSuggestionIndex = (activeSuggestionIndex + 1) % items.length;
        updateActiveSuggestion(items);
    }

    if (e.key === "ArrowUp") {
        e.preventDefault();
        activeSuggestionIndex = (activeSuggestionIndex - 1 + items.length) % items.length;
        updateActiveSuggestion(items);
    }

    if (e.key === "Enter") {
        if (activeSuggestionIndex >= 0) {
            items[activeSuggestionIndex].click();
        } else {
            document.getElementById("searchBtn").click();
        }
    }
});

function updateActiveSuggestion(items) {
    items.forEach(item => item.classList.remove("active-suggestion"));
    if (activeSuggestionIndex >= 0) {
        items[activeSuggestionIndex].classList.add("active-suggestion");
        items[activeSuggestionIndex].scrollIntoView({ block: "nearest" });
    }
}

async function fetchSuggestions(query) {
    activeSuggestionIndex = -1;
    const response = await fetch(`/api/search/${query}`);
    const data = await response.json();

    const suggestionsBox = document.getElementById("suggestions");
    suggestionsBox.innerHTML = "";

    if (!data.items || data.items.length === 0) return;

    data.items.slice(0, 5).forEach(game => {
        const item = document.createElement("div");
        item.className = "suggestion-item";

        const priceText = game.price
            ? (game.price.final === 0 ? "Free" : `$${(game.price.final / 100).toFixed(2)}`)
            : "N/A";

        item.innerHTML = `
            <img src="${game.tiny_image}" alt="${game.name}">
            <div class="suggestion-info">
                <span class="suggestion-name">${game.name}</span>
                <span class="suggestion-dev">${priceText}</span>
            </div>
        `;

        item.addEventListener("click", () => {
            suggestionsBox.innerHTML = "";
            searchGame(game.name);
        });

        suggestionsBox.appendChild(item);
    });
}

/* ==========================================================
   LOAD REAL GAME DATA FROM NIMLYX BACKEND
========================================================== */

const params = new URLSearchParams(window.location.search);
const gameName = params.get("q");
document.getElementById("gameInput").value = gameName || "";

async function loadGame() {
    if (!gameName) return;

    try {
        const response = await fetch(`/api/find/${gameName}`);
        const game = await response.json();
        renderGame(game);
    } catch (error) {
        console.error("Error loading game:", error);
    }
}

loadGame();

/* ==========================================================
   MASTER RENDER
========================================================== */

function renderGame(game) {
    renderHero(game);
    renderAbout(game);
    renderScreenshots(game);
    renderTrailer(game);
    renderGenres(game);
    renderCredits(game);
    renderScore(game);
    renderStats(game);
    initScrollReveal();
}

/* ---------------- HERO ---------------- */

function renderHero(game) {
    document.getElementById("heroBg").src = game.header_image || "";
    document.getElementById("heroBg").alt = game.name || "";

    document.getElementById("heroKicker").textContent = game.genres.join(" · ");
    document.getElementById("heroTitle").textContent = game.name;

    const scoreClass = game.metacritic >= 75 ? "is-good" : game.metacritic >= 50 ? "is-mid" : "is-low";

    const platformNames = Object.keys(game.platforms)
        .filter(p => game.platforms[p])
        .map(p => p.charAt(0).toUpperCase() + p.slice(1));

    document.getElementById("heroMeta").innerHTML = `
        <span class="meta-chip meta-chip--price"><i class="fa-solid fa-tag"></i>${game.price}</span>
        <span class="meta-chip"><i class="fa-regular fa-calendar"></i>${game.release_date || "TBA"}</span>
        ${game.metacritic ? `<span class="meta-chip meta-chip--score ${scoreClass}"><i class="fa-solid fa-star"></i>${game.metacritic} Metacritic</span>` : ""}
        <span class="meta-chip"><i class="fa-solid fa-users"></i>${game.total_reviews.toLocaleString()} Reviews</span>
        <span class="meta-chip"><i class="fa-solid fa-desktop"></i>${platformNames.join(" / ")}</span>
    `;

    const steamLink = document.getElementById("steamLink");
    if (steamLink) {
        steamLink.href = `https://store.steampowered.com/search/?term=${encodeURIComponent(game.name)}`;
    }
}

/* ---------------- ABOUT ---------------- */

function renderAbout(game) {
    document.getElementById("aboutText").innerHTML = `<p>${game.short_description || "No description available."}</p>`;
}

/* ---------------- SCREENSHOTS ---------------- */

function renderScreenshots(game) {
    const featuredImg = document.getElementById("featuredImg");
    const thumbStrip = document.getElementById("thumbStrip");
    const wrap = document.querySelector(".featured-wrap");

    const shots = game.screenshots || [];

    if (shots.length === 0) {
        if (wrap) wrap.style.display = "none";
        return;
    }
    if (wrap) wrap.style.display = "";

    featuredImg.src = shots[0];

    thumbStrip.innerHTML = shots.map((url, i) => `
        <button class="thumb ${i === 0 ? "is-active" : ""}" data-index="${i}" aria-label="Screenshot ${i + 1}">
            <img src="${url}" alt="">
        </button>
    `).join("");

    thumbStrip.addEventListener("click", (e) => {
        const btn = e.target.closest(".thumb");
        if (!btn) return;
        const index = Number(btn.dataset.index);

        featuredImg.src = shots[index];
        featuredImg.style.animation = "none";
        featuredImg.offsetHeight;
        featuredImg.style.animation = "";

        thumbStrip.querySelectorAll(".thumb").forEach(t => t.classList.remove("is-active"));
        btn.classList.add("is-active");
    });

    document.getElementById("stripPrev").addEventListener("click", () => thumbStrip.scrollBy({ left: -320, behavior: "smooth" }));
    document.getElementById("stripNext").addEventListener("click", () => thumbStrip.scrollBy({ left: 320, behavior: "smooth" }));
}

/* ---------------- TRAILER ---------------- */

function renderTrailer(game) {
    const trailerFrame = document.getElementById("trailerFrame");
    const movie = (game.movies || [])[0];

    if (movie && movie.video_url) {
        trailerFrame.innerHTML = `
            <div class="trailer__player">
                <video controls preload="metadata" poster="${movie.thumbnail || ""}">
                    <source src="${movie.video_url}" type="video/mp4">
                </video>
            </div>`;
    } else {
        trailerFrame.innerHTML = `
            <div class="trailer__empty">
                <i class="fa-solid fa-video-slash"></i>
                <span>No trailer available</span>
                <small>Check back once Nimlyx adds full video support.</small>
            </div>`;
    }

    document.getElementById("watchTrailerBtn").addEventListener("click", () => {
        document.getElementById("trailerSection").scrollIntoView({ behavior: "smooth", block: "center" });
    });
}

/* ---------------- GENRES ---------------- */

function renderGenres(game) {
    document.getElementById("genreList").innerHTML = (game.genres || [])
        .map(g => `<span class="genre-pill">${g}</span>`)
        .join("");
}

/* ---------------- CREDITS ---------------- */

function renderCredits(game) {
    document.getElementById("devValue").textContent = (game.developers || []).join(", ") || "Unknown";
    document.getElementById("pubValue").textContent = (game.publishers || []).join(", ") || "Unknown";
}

/* ---------------- NIMLYX SCORE ---------------- */

function computeNimlyxScore(game) {
    if (game.metacritic) {
        return {
            value: game.metacritic,
            verdict: game.metacritic >= 85 ? "Excellent" : game.metacritic >= 70 ? "Very Good" : game.metacritic >= 50 ? "Mixed" : "Poor",
            note: "Based on Metacritic critic score."
        };
    }
    const estimate = Math.min(95, Math.round(50 + Math.log10(game.total_reviews + 1) * 8));
    return {
        value: estimate,
        verdict: estimate >= 80 ? "Well Received" : estimate >= 60 ? "Generally Positive" : "Limited Data",
        note: "Estimated from review volume (no Metacritic score available)."
    };
}

function renderScore(game) {
    const nimlyxScore = computeNimlyxScore(game);

    const RADIUS = 56;
    const CIRC = 2 * Math.PI * RADIUS;
    const progressEl = document.getElementById("scoreProgress");
    progressEl.style.strokeDasharray = `${CIRC}`;
    progressEl.style.strokeDashoffset = `${CIRC}`;

    document.getElementById("scoreVerdict").textContent = nimlyxScore.verdict;
    document.getElementById("scoreNote").textContent = nimlyxScore.note;

    requestAnimationFrame(() => {
        const offset = CIRC - (CIRC * nimlyxScore.value) / 100;
        progressEl.style.strokeDashoffset = `${offset}`;
    });

    (function animateScoreValue() {
        const el = document.getElementById("scoreValue");
        const target = nimlyxScore.value;
        const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        if (reduceMotion) { el.textContent = target; return; }
        let current = 0;
        const step = () => {
            current += Math.ceil((target - current) / 6) || 1;
            if (current >= target) { el.textContent = target; return; }
            el.textContent = current;
            requestAnimationFrame(step);
        };
        requestAnimationFrame(step);
    })();
}

/* ---------------- QUICK STATS ---------------- */

function renderStats(game) {
    const scoreClass = game.metacritic >= 75 ? "is-good" : game.metacritic >= 50 ? "is-mid" : "is-low";

    const platformNames = Object.keys(game.platforms)
        .filter(p => game.platforms[p])
        .map(p => p.charAt(0).toUpperCase() + p.slice(1));

    document.getElementById("statsRows").innerHTML = `
        <div class="info-row">
            <span class="info-row__label"><i class="fa-solid fa-tag"></i>Price</span>
            <span class="info-row__value">${game.price}</span>
        </div>
        ${game.metacritic ? `
        <div class="info-row">
            <span class="info-row__label"><i class="fa-solid fa-star"></i>Metacritic</span>
            <span class="info-row__value ${scoreClass === "is-good" ? "is-good" : ""}">${game.metacritic} / 100</span>
        </div>` : ""}
        <div class="info-row">
            <span class="info-row__label"><i class="fa-solid fa-users"></i>Reviews</span>
            <span class="info-row__value">${game.total_reviews.toLocaleString()}</span>
        </div>
        <div class="info-row">
            <span class="info-row__label"><i class="fa-solid fa-desktop"></i>Platforms</span>
            <span class="info-row__value">${platformNames.map(p => `<span class="mini-badge">${p}</span>`).join("")}</span>
        </div>
        <div class="info-row">
            <span class="info-row__label"><i class="fa-solid fa-tags"></i>Genres</span>
            <span class="info-row__value">${(game.genres || []).map(g => `<span class="mini-badge">${g}</span>`).join("") || "—"}</span>
        </div>
        <div class="info-row">
            <span class="info-row__label"><i class="fa-regular fa-calendar"></i>Release</span>
            <span class="info-row__value">${game.release_date || "TBA"}</span>
        </div>
    `;
}

/* ==========================================================
   SCROLL REVEAL
========================================================== */

function initScrollReveal() {
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!reduceMotion && "IntersectionObserver" in window) {
        const io = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    entry.target.classList.add("in-view");
                    io.unobserve(entry.target);
                }
            });
        }, { threshold: 0.12 });
        document.querySelectorAll(".reveal").forEach(el => io.observe(el));
    } else {
        document.querySelectorAll(".reveal").forEach(el => el.classList.add("in-view"));
    }
}