/* SALT Portal Web Push */

(function () {

    async function enableSALTWebPush() {

        if (!("serviceWorker" in navigator)) {
            alert("Your browser does not support service workers.");
            return false;
        }

        if (!("PushManager" in window) ||
            !("Notification" in window)) {
            alert("Your browser does not support desktop notifications.");
            return false;
        }

        try {

            const registration =
                await navigator.serviceWorker.register(
                    "/static/js/service-worker.js"
                );

            const permission =
                await Notification.requestPermission();

            if (permission !== "granted") {
                console.warn("SALT notifications were not allowed.");
                return false;
            }

            const keyResponse =
                await fetch("/api/push/public-key");

            if (!keyResponse.ok) {
                throw new Error("Could not get VAPID public key.");
            }

            const keyData =
                await keyResponse.json();

            if (!keyData.publicKey) {
                throw new Error("VAPID public key is not configured.");
            }

            const applicationServerKey =
                urlBase64ToUint8Array(keyData.publicKey);

            let subscription =
                await registration.pushManager.getSubscription();

            if (!subscription) {

                subscription =
                    await registration.pushManager.subscribe({
                        userVisibleOnly: true,
                        applicationServerKey
                    });
            }

            const saveResponse =
                await fetch("/api/push/subscribe", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify(
                        subscription.toJSON()
                    )
                });

            if (!saveResponse.ok) {
                throw new Error("Could not save push subscription.");
            }

            console.log("SALT desktop notifications enabled.");
            return true;

        } catch (error) {

            console.error(
                "SALT web push setup failed:",
                error
            );

            return false;
        }
    }

    function urlBase64ToUint8Array(base64String) {

        const padding =
            "=".repeat(
                (4 - base64String.length % 4) % 4
            );

        const base64 =
            (base64String + padding)
                .replace(/-/g, "+")
                .replace(/_/g, "/");

        const rawData =
            window.atob(base64);

        return Uint8Array.from(
            [...rawData].map(
                char => char.charCodeAt(0)
            )
        );
    }

    window.enableSALTWebPush =
        enableSALTWebPush;

})();
