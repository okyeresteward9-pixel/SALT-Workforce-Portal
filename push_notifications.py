"""SALT Portal Web Push helper."""

import json
import os

from pywebpush import webpush, WebPushException


def get_vapid_public_key():
    return os.environ.get("VAPID_PUBLIC_KEY", "")


def send_web_push(subscription, title, body, url="/dashboard", tag="salt-portal",
                  on_expired=None):
    private_key = os.environ.get("VAPID_PRIVATE_KEY")

    if not private_key:
        return False

    claim_email = os.environ.get(
        "VAPID_CLAIM_EMAIL",
        "mailto:admin@saltuniversity.edu.gh"
    )

    payload = {
        "title": title,
        "body": body,
        "url": url,
        "tag": tag
    }

    try:
        webpush(
            subscription_info=subscription,
            data=json.dumps(payload),
            vapid_private_key=private_key,
            vapid_claims={
                "sub": claim_email
            }
        )
        return True

    except WebPushException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)

        if status in (404, 410):
            # The browser unsubscribed or the subscription expired for good.
            # Let the caller delete it instead of retrying it forever.
            if on_expired:
                try:
                    on_expired(subscription.get("endpoint"))
                except Exception as cleanup_exc:
                    print("WEB PUSH CLEANUP ERROR:", repr(cleanup_exc))
        else:
            print(
                "WEB PUSH DELIVERY FAILED:",
                repr(exc)
            )
        return False

    except Exception as exc:
        print(
            "WEB PUSH ERROR:",
            repr(exc)
        )
        return False
