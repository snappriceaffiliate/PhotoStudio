from django.db import connection
from django.http import JsonResponse


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
