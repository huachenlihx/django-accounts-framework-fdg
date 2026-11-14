"""Rate limits for public, unauthenticated account endpoints.

The activation-resend endpoint accepts any email address and sends mail, so it is
limited twice:

* per client IP  - stops one machine from spraying requests at many addresses;
* per email      - stops many machines from flooding one victim's inbox.

The per-email limit counts requests for an address whether or not an account exists, so
a 429 never reveals whether the address is registered.

Rates use DRF's "N/second|minute|hour|day" format and can be changed (or disabled by
setting them to None) in settings.ACCOUNTS_FRAMEWORK:
    ACTIVATION_RESEND_RATE_PER_IP     (default "5/hour")
    ACTIVATION_RESEND_RATE_PER_EMAIL  (default "3/hour")

Counters live in Django's cache. The default LocMemCache is per process, so with several
server workers use a shared cache (Redis, Memcached, database) in production.
"""
from __future__ import annotations

import hashlib

from rest_framework.throttling import SimpleRateThrottle

from .conf import accounts_setting


class ResendActivationIPThrottle(SimpleRateThrottle):
    scope = "activation_resend_ip"

    def get_rate(self):
        return accounts_setting("ACTIVATION_RESEND_RATE_PER_IP", "5/hour")

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class ResendActivationEmailThrottle(SimpleRateThrottle):
    scope = "activation_resend_email"

    def get_rate(self):
        return accounts_setting("ACTIVATION_RESEND_RATE_PER_EMAIL", "3/hour")

    def get_cache_key(self, request, view):
        raw = request.data.get("email", "") if hasattr(request.data, "get") else ""
        email = raw.strip().lower() if isinstance(raw, str) else ""
        if not email:
            return None  # nothing to key on; the per-IP limit still applies
        digest = hashlib.sha256(email.encode("utf-8")).hexdigest()
        return self.cache_format % {"scope": self.scope, "ident": digest}
