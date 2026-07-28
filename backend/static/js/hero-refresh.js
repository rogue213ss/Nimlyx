/* ==========================================================
   HERO REFRESH — auto-updates the homepage once a background
   Insight Engine build finishes, with no manual reload needed.

   Only runs at all if #heroPendingNotice exists in the page — that
   element is only server-rendered when routes/pages.py detects a
   background build is genuinely in progress for the visitor's
   region (see hero_pending in pages.py / /api/hero-status). If the
   build already finished with nothing to publish this cycle, that
   element is absent and this script does nothing — there's nothing
   to wait for, so it doesn't poll forever.

   On "ready", this does a full page reload rather than trying to
   patch the DOM in place. That's deliberate: hero-rotation.js and
   picks.js both wire up event listeners against specific element
   IDs at page load. Patching innerHTML without re-running that
   setup would leave the carousel/click-to-expand interactions
   silently broken. A reload re-initializes everything correctly,
   with no risk of half-wired JS state, for one extra page load that
   only ever happens once per visit.
========================================================== */

(function () {
    const notice = document.getElementById("heroPendingNotice");
    if (!notice) return;

    const POLL_INTERVAL_MS = 5000;
    const MAX_ATTEMPTS = 36; // ~3 minutes — a real safety cap, not an
                             // expected duration. If a build is still
                             // running after 3 minutes, something's
                             // wrong; stop polling rather than hammer
                             // the server forever. The visitor still
                             // sees the honest "preparing" notice,
                             // just without an automatic reload after
                             // this point — a manual refresh still
                             // works normally.

    let attempts = 0;

    function poll() {
        attempts += 1;

        fetch("/api/hero-status")
            .then((res) => res.json())
            .then((data) => {
                if (!data.pending) {
                    window.location.reload();
                    return;
                }
                if (attempts < MAX_ATTEMPTS) {
                    setTimeout(poll, POLL_INTERVAL_MS);
                }
            })
            .catch(() => {
                // A single failed status check isn't worth giving up
                // over — try again on the next interval, same cap.
                if (attempts < MAX_ATTEMPTS) {
                    setTimeout(poll, POLL_INTERVAL_MS);
                }
            });
    }

    setTimeout(poll, POLL_INTERVAL_MS);
})();
