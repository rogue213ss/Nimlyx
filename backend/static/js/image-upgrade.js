/* ==========================================================
   NIMLYX — PROGRESSIVE IMAGE UPGRADE

   Every card on the site already has a guaranteed image rendered by
   the server (header_image / header.jpg — the one asset Steam always
   returns). This module's only job is to try to do BETTER than that,
   never worse:

     1. Guaranteed image is already on screen before this ever runs.
     2. In the background, test each higher-res candidate URL with a
        real Image() load.
     3. Swap the visible <img src> / background-image ONLY on that
        candidate's onload firing.
     4. On onerror, move to the next candidate; if all fail, leave
        the guaranteed image exactly where it was — never a broken
        image, never a flash of empty space.
     5. Cache the winning (or failing) URL in localStorage so repeat
        page loads / repeat cards for the same game don't re-test.

   Backend never hands this module an unverified URL to render
   directly — see steam_images.build_image_candidates() and
   HeroCandidate.image_candidates.
========================================================== */

(function () {
    "use strict";

    const CACHE_KEY = "nimlyx:image-cache:v1";
    const CACHE_MAX_ENTRIES = 500; // keep localStorage from growing unbounded

    /* In-memory cache backs every lookup so repeat calls within the
       same page view never touch localStorage or fire a duplicate
       Image() probe, even before persistence has loaded/saved. */
    const memoryCache = new Map(); // url -> true | false
    const inFlight = new Map();    // url -> Promise<boolean>, de-dupes concurrent probes

    function loadPersistentCache() {
        try {
            const raw = window.localStorage.getItem(CACHE_KEY);
            return raw ? JSON.parse(raw) : {};
        } catch (err) {
            return {};
        }
    }

    let persistentCache = loadPersistentCache();

    function savePersistentCache() {
        try {
            const keys = Object.keys(persistentCache);
            if (keys.length > CACHE_MAX_ENTRIES) {
                // Trim oldest-inserted entries first (insertion order in
                // plain objects is preserved for string keys).
                const overflow = keys.length - CACHE_MAX_ENTRIES;
                keys.slice(0, overflow).forEach((k) => delete persistentCache[k]);
            }
            window.localStorage.setItem(CACHE_KEY, JSON.stringify(persistentCache));
        } catch (err) {
            // Storage disabled/full — fine, this is purely an
            // optimization, never required for correctness.
        }
    }

    function rememberResult(url, ok) {
        memoryCache.set(url, ok);
        persistentCache[url] = ok ? 1 : 0;
        savePersistentCache();
    }

    function knownResult(url) {
        if (memoryCache.has(url)) return memoryCache.get(url);
        if (Object.prototype.hasOwnProperty.call(persistentCache, url)) {
            const ok = persistentCache[url] === 1;
            memoryCache.set(url, ok);
            return ok;
        }
        return undefined; // not yet tested, either session
    }

    /* Resolves true/false — never rejects — so callers never need a
       .catch(). A cached "known bad" result resolves false without
       ever creating a new Image(). */
    function probe(url) {
        const known = knownResult(url);
        if (known !== undefined) return Promise.resolve(known);

        if (inFlight.has(url)) return inFlight.get(url);

        const promise = new Promise((resolve) => {
            const tester = new Image();
            tester.onload = () => {
                rememberResult(url, true);
                resolve(true);
            };
            tester.onerror = () => {
                rememberResult(url, false);
                resolve(false);
            };
            tester.src = url;
        }).finally(() => {
            inFlight.delete(url);
        });

        inFlight.set(url, promise);
        return promise;
    }

    /* Tries candidates in order, returns the first URL that actually
       loads, or null if every candidate fails. Candidates are tried
       sequentially (not all at once) so a working first candidate
       doesn't waste bandwidth firing requests for the rest. */
    async function pickFirstWorking(candidates) {
        for (const url of candidates || []) {
            if (!url) continue;
            const ok = await probe(url);
            if (ok) return url;
        }
        return null;
    }

    function parseCandidates(raw) {
        if (!raw) return [];
        if (Array.isArray(raw)) return raw;
        try {
            const parsed = JSON.parse(raw);
            return Array.isArray(parsed) ? parsed : [];
        } catch (err) {
            return [];
        }
    }

    /* Upgrades a real <img> element. The element's current src (the
       guaranteed image) is left completely alone until/unless a
       candidate wins. */
    async function upgradeImg(imgEl, candidates) {
        if (!imgEl) return;
        const list = parseCandidates(candidates);
        if (!list.length) return;

        const winner = await pickFirstWorking(list);
        if (winner && imgEl.isConnected) {
            imgEl.src = winner;
        }
    }

    /* Same idea for elements using a CSS background-image (hero
       slides, the Picks lead panel) instead of an <img> tag. */
    async function upgradeBackground(el, candidates) {
        if (!el) return;
        const list = parseCandidates(candidates);
        if (!list.length) return;

        const winner = await pickFirstWorking(list);
        if (winner && el.isConnected) {
            el.style.backgroundImage = `url('${winner}')`;
        }
    }

    /* Auto-wires every element in `root` (default: whole document)
       carrying data-img-candidates or data-bg-candidates. Safe to
       call more than once — already-upgraded elements just get
       re-probed against the same cache, which resolves instantly. */
    function upgradeAll(root) {
        const scope = root || document;

        scope.querySelectorAll("[data-img-candidates]").forEach((el) => {
            upgradeImg(el, el.dataset.imgCandidates);
        });

        scope.querySelectorAll("[data-bg-candidates]").forEach((el) => {
            upgradeBackground(el, el.dataset.bgCandidates);
        });
    }

    window.NimlyxImageUpgrade = {
        upgradeImg,
        upgradeBackground,
        upgradeAll,
        parseCandidates,
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", () => upgradeAll());
    } else {
        upgradeAll();
    }
})();
