/* SALT Workforce PWA bootstrap.
 * Registers the service worker, shows an "update available" banner,
 * handles the install prompt and online/offline state.
 * Safe to include more than once on a page.
 */
(function () {
    if (window.__saltPwaLoaded) return;
    window.__saltPwaLoaded = true;

    // ------------------------------------------------------ update banner
    function showUpdateBanner(registration) {
        if (document.getElementById('saltUpdateBanner')) return;

        const bar = document.createElement('div');
        bar.id = 'saltUpdateBanner';
        bar.setAttribute('role', 'status');
        bar.style.cssText = [
            'position:fixed', 'left:12px', 'right:12px',
            'bottom:calc(12px + env(safe-area-inset-bottom, 0px))',
            'z-index:2147483000', 'max-width:460px', 'margin:0 auto',
            'display:flex', 'align-items:center', 'gap:10px',
            'padding:12px 14px', 'border-radius:14px',
            'background:#0b3d91', 'color:#fff',
            'font:600 14px/1.35 Inter,Segoe UI,Arial,sans-serif',
            'box-shadow:0 10px 30px rgba(0,0,0,.28)'
        ].join(';');

        const text = document.createElement('span');
        text.style.flex = '1';
        text.textContent = 'A new version of SALT Workforce is ready.';

        function button(label, primary) {
            const b = document.createElement('button');
            b.type = 'button';
            b.textContent = label;
            b.style.cssText = [
                'border:0', 'border-radius:10px', 'padding:8px 12px',
                'font:700 13px Inter,Segoe UI,Arial,sans-serif', 'cursor:pointer',
                primary ? 'background:#fff;color:#0b3d91' : 'background:transparent;color:#cfe0ff'
            ].join(';');
            return b;
        }

        const refresh = button('Refresh', true);
        const later = button('Later', false);

        refresh.addEventListener('click', function () {
            const waiting = registration && registration.waiting;
            if (waiting) {
                waiting.postMessage({ type: 'SKIP_WAITING' }); // page reloads on controllerchange
            } else {
                window.location.reload();
            }
        });
        later.addEventListener('click', function () { bar.remove(); });

        bar.appendChild(text);
        bar.appendChild(refresh);
        bar.appendChild(later);
        document.body.appendChild(bar);
    }

    // --------------------------------------------------- service worker
    if ('serviceWorker' in navigator) {
        const hadController = !!navigator.serviceWorker.controller;
        let reloading = false;

        navigator.serviceWorker.addEventListener('controllerchange', function () {
            // Reload once when a NEW version takes over (not on first install).
            if (!hadController || reloading) return;
            reloading = true;
            window.location.reload();
        });

        window.addEventListener('load', async function () {
            try {
                const registration = await navigator.serviceWorker.register('/service-worker.js', {
                    scope: '/',
                    updateViaCache: 'none'
                });

                function announceUpdate() {
                    window.dispatchEvent(new CustomEvent('salt-pwa-update', { detail: { registration: registration } }));
                    showUpdateBanner(registration);
                }

                if (registration.waiting && navigator.serviceWorker.controller) announceUpdate();

                registration.addEventListener('updatefound', function () {
                    const worker = registration.installing;
                    if (!worker) return;
                    worker.addEventListener('statechange', function () {
                        if (worker.state === 'installed' && navigator.serviceWorker.controller) announceUpdate();
                    });
                });

                // Installed apps can stay open for days: look for new versions
                // every hour and whenever the app comes back to the foreground.
                let lastCheck = Date.now();
                function checkForUpdate() {
                    lastCheck = Date.now();
                    registration.update().catch(function () {});
                }
                setInterval(checkForUpdate, 60 * 60 * 1000);
                document.addEventListener('visibilitychange', function () {
                    if (document.visibilityState === 'visible' && Date.now() - lastCheck > 10 * 60 * 1000) {
                        checkForUpdate();
                    }
                });
            } catch (error) {
                console.error('SALT PWA registration failed:', error);
            }
        });
    }

    // ------------------------------------------------------ install prompt
    let deferredPrompt = null;

    window.addEventListener('beforeinstallprompt', function (event) {
        event.preventDefault();
        deferredPrompt = event;
        window.dispatchEvent(new Event('salt-install-available'));
    });

    window.SALTInstallApp = async function () {
        if (!deferredPrompt) return false;
        deferredPrompt.prompt();
        const choice = await deferredPrompt.userChoice;
        deferredPrompt = null;
        window.dispatchEvent(new Event('salt-install-finished'));
        return choice.outcome === 'accepted';
    };

    window.addEventListener('appinstalled', function () {
        deferredPrompt = null;
        window.dispatchEvent(new Event('salt-app-installed'));
    });

    // ------------------------------------------------------ online / offline
    window.addEventListener('online', function () {
        document.documentElement.classList.remove('salt-offline');
        window.dispatchEvent(new Event('salt-online'));
    });
    window.addEventListener('offline', function () {
        document.documentElement.classList.add('salt-offline');
        window.dispatchEvent(new Event('salt-offline'));
    });
    if (!navigator.onLine) document.documentElement.classList.add('salt-offline');
})();
