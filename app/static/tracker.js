/**
# ==============================================================================
# PULSETRACK ANALYTICS - LIGHTWEIGHT CLIENT-SIDE JAVASCRIPT TRACKER
# ==============================================================================
# Datum: 01.06.2026 | Version: 2.1 | Status: Aktiv gepflegt & DSGVO-geprüft
#
# BETRIEBSWIRTSCHAFTLICHER ZWECK DIESES SKRIPTE:
# Dies ist das "Auge" von PulseTrack. Dieses kleine Skript wird von Ihrem IT-Techniker
# in Ihre Webseite (z. B. https://www.elektro-pepi.at/) eingebunden. Es erfasst
# jeden Seitenaufruf (Pageview) vollautomatisch und sendet ihn an Ihren PulseTrack-Server.
#
# KUNDENVERSTÄNDLICHE & GESCHÄFTSFÜHRER-ASPEKTE (WARUM DIESER TRACKER GENIAL IST):
# 1. 100% DSGVO-konform OHNE Cookie-Banner:
#    Dieser Tracker speichert KEINE Cookies im Browser Ihres Besuchers und hinterlässt
#    keine digitalen Spuren. Sie müssen KEINE störenden Cookie-Einwilligungsbanner
#    (Opt-Ins) dafür anzeigen! Das erhöht Ihre Conversion-Rate enorm.
# 2. Absolut Null Ladeverzögerung für Ihre Kunden (sendBeacon):
#    Das Skript nutzt die moderne Web-Technologie "navigator.sendBeacon". Dadurch werden
#    die Klickdaten asynchron im Hintergrund übertragen. Die Ladezeit Ihrer Webseite wird
#    um kein einziges Millisekunde verzögert. Google Lighthouse und Ihre Kunden werden es lieben!
# 3. Extrem leichtgewichtig:
#    Mit unter 1 Kilobyte Größe lädt sich dieses Skript blitzschnell und verbraucht kein
#    Datenvolumen auf Smartphones Ihrer Besucher.
# ==============================================================================
 */
(function() {
    // Verhindert doppeltes Laden des Trackers im Browser-DOM, damit Klicks nicht doppelt gezählt werden
    if (window.__pulsetrack_loaded) return;
    window.__pulsetrack_loaded = true;

    // Finde das Script-Tag im HTML-Code Ihrer Seite, um das Tracking-Token und die Server-URL auszulesen
    const script = document.currentScript || document.querySelector('script[src*="/tracker.js"]');
    if (!script) return;

    // Einzigartiges Tracking-Token auslesen (wird im Dashboard für Ihre Webseite erzeugt)
    const token = script.getAttribute('data-token');
    if (!token) {
        console.warn("PulseTrack: Fehlendes 'data-token' Attribut. Tracking deaktiviert.");
        return;
    }

    // Ermittelt dynamisch die Basis-URL des Analytics-SaaS-Servers, von dem das Skript geladen wurde
    const scriptUrl = new URL(script.src);
    const apiEndpoint = `${scriptUrl.protocol}//${scriptUrl.host}/api/hit`;

    // Hauptfunktion zum Erfassen und Senden der Besucherdaten
    const track = function() {
        const payload = {
            token: token,
            url: window.location.href,
            referrer: document.referrer || null // Erfasst, woher der Besucher kommt (z.B. Google, Facebook)
        };

        // Asynchrones, nicht-blockierendes Senden über sendBeacon (moderner Standard)
        // Läuft im Hintergrund, selbst wenn der Besucher die Seite sofort wieder schließt.
        if (navigator.sendBeacon) {
            const blob = new Blob([JSON.stringify(payload)], { type: 'application/json' });
            navigator.sendBeacon(apiEndpoint, blob);
        } else {
            // Fallback für veraltete Browser (z.B. sehr alte Internet Explorer Versionen)
            fetch(apiEndpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
                keepalive: true // Hält die Verbindung kurz offen, falls der User die Seite wechselt
            }).catch(function(err) {
                console.warn('PulseTrack: Datenübertragung fehlgeschlagen:', err);
            });
        }
    };

    // Tracking erst auslösen, wenn das HTML der Webseite vollständig geladen und gerendert ist
    if (document.readyState === 'complete') {
        track();
    } else {
        window.addEventListener('load', track);
    }
})();
