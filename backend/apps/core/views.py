from django.conf import settings
from django.db import connection
from django.http import FileResponse, Http404, JsonResponse
from django.views.decorators.csrf import ensure_csrf_cookie


def health(request):
    """Liveness and database check used by the hosting platform and the smoke test."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        database = "ok"
    except Exception:  # noqa: BLE001 - report any database failure as unhealthy
        database = "error"
    status = 200 if database == "ok" else 503
    return JsonResponse(
        {"status": "ok" if status == 200 else "error", "database": database}, status=status
    )


@ensure_csrf_cookie
def spa(request):
    """Serve the built React app for every screen path (production image only)."""
    index = settings.FRONTEND_DIST / "index.html"
    if not index.exists():
        raise Http404("The React app is served by Vite in development: open port 5173.")
    response = FileResponse(index.open("rb"), content_type="text/html")
    response["Cache-Control"] = "no-cache"
    return response
