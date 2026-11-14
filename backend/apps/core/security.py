"""Extra browser security headers: Content-Security-Policy and Permissions-Policy.

The CSP starts in report-only mode (CSP_ENFORCE=false): browsers log what would be
blocked without blocking it. Check Razorpay Checkout and photo loading on staging with the
browser console open, then set CSP_ENFORCE=true.
"""

from urllib.parse import urlsplit

from django.conf import settings


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else ""


def build_csp() -> str:
    storage = _origin(settings.S3_ENDPOINT_PUBLIC)
    razorpay = "https://checkout.razorpay.com https://api.razorpay.com"
    directives = {
        "default-src": "'self'",
        "script-src": "'self' https://checkout.razorpay.com",
        # React sets a few inline style attributes (progress bars); no inline scripts.
        "style-src": "'self' 'unsafe-inline'",
        "img-src": f"'self' data: blob: {storage}",
        "connect-src": f"'self' {storage} {razorpay}",
        "frame-src": razorpay,
        "worker-src": "'self' blob:",
        "font-src": "'self'",
        "object-src": "'none'",
        "base-uri": "'self'",
        "form-action": "'self'",
        "frame-ancestors": "'none'",
    }
    return "; ".join(f"{name} {value}".strip() for name, value in directives.items())


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.csp = build_csp()
        self.csp_header = (
            "Content-Security-Policy"
            if settings.CSP_ENFORCE
            else "Content-Security-Policy-Report-Only"
        )

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=(), usb=()"
        )
        is_html = response.get("Content-Type", "").startswith("text/html")
        # The Django admin ships its own scripts and styles; the policy targets the React app.
        if is_html and not request.path.startswith("/admin/"):
            response.setdefault(self.csp_header, self.csp)
        return response
