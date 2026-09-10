/* SALT Workforce PWA bootstrap */
(function () {
    if (!('serviceWorker' in navigator)) return;

    window.addEventListener('load', async function () {
        try {
            const registration = await navigator.serviceWorker.register('/service-worker.js', {
                scope: '/'
            });

            registration.addEventListener('updatefound', function () {
                const worker = registration.installing;
                if (!worker) return;
                worker.addEventListener('statechange', function () {
                    if (worker.state === 'installed' && navigator.serviceWorker.controller) {
                        window.dispatchEvent(new CustomEvent('salt-pwa-update', {
                            detail: { registration: registration }
                        }));
                    }
                });
            });

            if (registration.waiting && navigator.serviceWorker.controller) {
                window.dispatchEvent(new CustomEvent('salt-pwa-update', {
                    detail: { registration: registration }
                }));
            }
        } catch (error) {
            console.error('SALT PWA registration failed:', error);
        }
    });

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

    window.addEventListener('online', function () {
        document.documentElement.classList.remove('salt-offline');
        window.dispatchEvent(new Event('salt-online'));
    });

    window.addEventListener('offline', function () {
        document.documentElement.classList.add('salt-offline');
        window.dispatchEvent(new Event('salt-offline'));
    });

    if (!navigator.onLine) {
        document.documentElement.classList.add('salt-offline');
    }
})();
