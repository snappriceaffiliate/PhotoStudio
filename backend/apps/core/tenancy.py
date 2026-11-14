"""Tenant isolation, layer two: PostgreSQL row-level security (RLS).

Layer one is application scoping: every view reads tenant-owned rows through
`Model.objects.for_studio(request.studio_id)`.

Layer two is enforced by PostgreSQL. Each tenant-owned table gets a policy that only
shows rows whose studio_id matches the `app.current_studio` setting on the database
connection. TenantMiddleware sets it from the logged-in user on every request and clears
it afterwards, so a missed filter in a view returns nothing from another studio.

Platform-level work (Django admin for platform staff, background jobs that touch many
studios, management commands) runs inside `bypass_rls()`.

The application must connect as a role that is not a PostgreSQL superuser, because
superusers ignore RLS. Policies are FORCEd so they also apply to the table owner.
"""

from contextlib import contextmanager

from django.db import connection, migrations

STUDIO_SETTING = "app.current_studio"
BYPASS_SETTING = "app.bypass_rls"


def _set(name: str, value: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config(%s, %s, false)", [name, value])


def set_current_studio(studio_id) -> None:
    _set(STUDIO_SETTING, str(studio_id) if studio_id else "")


def set_bypass(enabled: bool) -> None:
    _set(BYPASS_SETTING, "on" if enabled else "")


def clear() -> None:
    set_current_studio(None)
    set_bypass(False)


@contextmanager
def studio_context(studio_id):
    """Run a block as one studio (used by jobs and tests)."""
    set_current_studio(studio_id)
    try:
        yield
    finally:
        set_current_studio(None)


@contextmanager
def bypass_rls():
    """Run a block with RLS off: platform admin, cross-studio jobs, management commands."""
    set_bypass(True)
    try:
        yield
    finally:
        set_bypass(False)


def enable_rls(table: str) -> migrations.RunSQL:
    """Migration operation that turns on RLS for one tenant-owned table."""
    policy = (
        f"current_setting('{BYPASS_SETTING}', true) = 'on' "
        f"OR studio_id = nullif(current_setting('{STUDIO_SETTING}', true), '')::uuid"
    )
    return migrations.RunSQL(
        sql=[
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
            f"CREATE POLICY tenant_isolation ON {table} USING ({policy}) WITH CHECK ({policy})",
        ],
        reverse_sql=[
            f"DROP POLICY IF EXISTS tenant_isolation ON {table}",
            f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY",
            f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY",
        ],
    )


class TenantMiddleware:
    """Sets the current studio on the database connection for each request.

    Must run after AuthenticationMiddleware. Sets `request.studio_id` for views.
    Client gallery requests (/api/v1/client/) use the studio of the client's event,
    stored in the session at client login; everything else uses the logged-in user.
    """

    CLIENT_PREFIX = "/api/v1/client/"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if request.path.startswith(self.CLIENT_PREFIX):
            studio_id = request.session.get("client_studio_id")
        else:
            studio_id = getattr(user, "studio_id", None) if user.is_authenticated else None
        platform_admin = (
            user.is_authenticated and user.is_staff and request.path.startswith("/admin/")
        )
        request.studio_id = studio_id
        set_current_studio(studio_id)
        set_bypass(platform_admin)
        try:
            return self.get_response(request)
        finally:
            clear()
