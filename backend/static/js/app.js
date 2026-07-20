/* ==========================================================
   HELPER — search a game (used everywhere a card is clicked)
========================================================== */

function searchGame(name) {
    window.location.href = `/search?q=${encodeURIComponent(name)}`;
}

/* ==========================================================
   HERO — FEATURED GAME SPOTLIGHT
   Isolated addition. Fetches GET /api/featured and reads the
   `hero` array only:
     [{ appid, name, header_image, short_description, price }]
========================================================== */

(function () {
    const ROTATE_MS = 10000;
    const FADE_MS = 380;

    let heroGames = [];
    let heroIndex = 0;
    let rotateTimer = null;

    async function initHero() {
        const heroSection = document.getElementById("heroSection");
        if (!heroSection) return;

        try {
            const response = await fetch("/api/featured");
            const data = await response.json();

            if (!Array.isArray(data.hero) || data.hero.length === 0) return;

            heroGames = data.hero;

            buildIndicators();
            renderSlide(0, false);
            bindInteractions();
            startRotation();
        } catch (error) {
            console.error("Error loading hero:", error);
        }
    }

    function buildIndicators() {
        const dotsContainer = document.getElementById("heroIndicators");
        dotsContainer.innerHTML = "";

        heroGames.forEach((game, i) => {
            const dot = document.createElement("button");
            dot.type = "button";
            dot.className = "hero-dot";
            dot.setAttribute("aria-label", `Show ${game.name}`);

            dot.addEventListener("click", (e) => {
                e.stopPropagation();
                if (i === heroIndex) return;
                renderSlide(i, true);
                restartRotation();
            });

            dotsContainer.appendChild(dot);
        });
    }

    function renderSlide(index, animate) {
        const game = heroGames[index];
        if (!game) return;

        const bgLayer = document.getElementById("heroBackground");
        const contentLayer = document.getElementById("heroContent");
        const titleEl = document.getElementById("heroTitle");
        const descEl = document.getElementById("heroDescription");

        const applySlideContent = () => {
            bgLayer.style.backgroundImage = `url("${game.header_image}")`;
            titleEl.textContent = game.name;
            descEl.textContent = game.short_description || "";
        };

        if (!animate) {
            applySlideContent();
        } else {
            bgLayer.classList.add("hero-fade-out");
            contentLayer.classList.add("hero-fade-out");

            setTimeout(() => {
                applySlideContent();
                bgLayer.classList.remove("hero-fade-out");
                contentLayer.classList.remove("hero-fade-out");
            }, FADE_MS);
        }

        document.querySelectorAll(".hero-dot").forEach((dot, i) => {
            dot.classList.toggle("active", i === index);
        });

        heroIndex = index;
    }

    function nextSlide() {
        const next = (heroIndex + 1) % heroGames.length;
        renderSlide(next, true);
    }

    function startRotation() {
        if (heroGames.length < 2) return;
        rotateTimer = setInterval(nextSlide, ROTATE_MS);
    }

    function restartRotation() {
        clearInterval(rotateTimer);
        startRotation();
    }

    function bindInteractions() {
        const heroSection = document.getElementById("heroSection");
        const ctaButton = document.getElementById("heroCta");

        heroSection.addEventListener("click", openGameSearch);

        ctaButton.addEventListener("click", (e) => {
            e.stopPropagation();
            openGameSearch();
        });
    }

    function openGameSearch() {
        const game = heroGames[heroIndex];
        if (!game) return;
        window.location.href = `/search?q=${encodeURIComponent(game.name)}`;
    }

    initHero();
})();

/* ==========================================================
   SEARCH BUTTON
========================================================== */

const searchBtn = document.getElementById("searchBtn");
if (searchBtn) {
    searchBtn.addEventListener("click", () => {
        const gameName = document.getElementById("gameInput").value.trim();
        if (!gameName) return;
        window.location.href = `/search?q=${encodeURIComponent(gameName)}`;
    });
}

document.getElementById("gameInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && searchBtn) {
        searchBtn.click();
    }
});

/* ==========================================================
   SEARCH SUGGESTIONS (debounced)
========================================================== */

let debounceTimer;

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

async function fetchSuggestions(query) {
    const response = await fetch(`/api/search/${query}`);
    const data = await response.json();

    const suggestionsBox = document.getElementById("suggestions");
    suggestionsBox.innerHTML = "";

    if (!data.items || data.items.length === 0) return;

    const topResults = data.items.slice(0, 5);

    topResults.forEach(game => {
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