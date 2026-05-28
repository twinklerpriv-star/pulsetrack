/**
 * PulseTrack - Multi-Tenant SaaS Client Tracker
 * 
 * Datum: 28.05.2026 | Version: 2.0 | Status: Aktiv gepflegt
 * 
 * Ein extrem leichtgewichtiger (< 1KB) JS-Tracker zur asynchronen, cookie-freien
 * Erfassung von Pageviews. Nutzt das data-token Attribut zur Zuordnung des Händlers.
 */
(function() {
    // Verhindert doppeltes Laden des Trackers im Browser-DOM
    if (window.__pulsetrack_loaded) return;
    window.__pulsetrack_loaded = true;

    // Finde das script-Tag, um Token und API-URL zu extrahieren
    const script = document.currentScript || document.querySelector('script[src*="/tracker.js"]');
    if (!script) return;

    // Einzigartiges Tracking-Token auslesen
    const token = script.getAttribute('data-token');
    if (!token) {
        console.warn("PulseTrack: Missing 'data-token' attribute. Analytics tracking disabled.");
        return;
    }

    // Ermittelt dynamisch die Basis-URL des Analytics-SaaS-Servers
    const scriptUrl = new URL(script.src);
    const apiEndpoint = `${scriptUrl.protocol}//${scriptUrl.host}/api/hit`;

    const track = function() {
        const payload = {
            token: token,
            url: window.location.href,
            referrer: document.referrer || null
        };

        // Asynchrones Senden über sendBeacon (blockiert das Rendern des Shops niemals)
        if (navigator.sendBeacon) {
            const blob = new Blob([JSON.stringify(payload)], { type: 'application/json' });
            navigator.sendBeacon(apiEndpoint, blob);
        } else {
            // Fallback für alte Browser
            fetch(apiEndpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
                keepalive: true
            }).catch(function(err) {
                console.warn('PulseTrack: Capture failed:', err);
            });
        }
    };

    // Tracking auslösen, sobald das DOM vollständig geladen ist
    if (document.readyState === 'complete') {
        track();
    } else {
        window.addEventListener('load', track);
    }
})();
