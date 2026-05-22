/**
 * PulseTrack - Client Tracker
 * 
 * Datum: 20.05.2026 | Version: 1.0 | Status: In Entwicklung
 * 
 * Ein extrem leichtgewichtiger JS-Tracker, der sich nahtlos in jede Webseite
 * einfügen lässt. Erhebt Seitenaufrufe vollkommen datenschutzkonform ohne Cookies.
 */
(function() {
    // Verhindert das doppelte Laden des Trackers
    if (window.__pulsetrack_loaded) return;
    window.__pulsetrack_loaded = true;

    const script = document.currentScript;
    if (!script) return;

    // Ermittelt dynamisch die Basis-URL des Analytics-Servers aus dem Script-Tag src
    const scriptUrl = new URL(script.src);
    const apiEndpoint = `${scriptUrl.protocol}//${scriptUrl.host}/api/hit`;

    const track = function() {
        const payload = {
            url: window.location.href,
            referrer: document.referrer || null
        };

        // Nutzt sendBeacon für zuverlässiges Senden im Hintergrund (verhindert Page-Load-Delay)
        if (navigator.sendBeacon) {
            navigator.sendBeacon(apiEndpoint, JSON.stringify(payload));
        } else {
            fetch(apiEndpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
                keepalive: true
            }).catch(function(err) {
                // Stiller Fail im Browser, um den Nutzer-Workflow nicht zu beeinträchtigen
                console.warn('Analytics capture failed:', err);
            });
        }
    };

    // Löst das Tracking aus, sobald die Seite bereit ist
    if (document.readyState === 'complete') {
        track();
    } else {
        window.addEventListener('load', track);
    }
})();
