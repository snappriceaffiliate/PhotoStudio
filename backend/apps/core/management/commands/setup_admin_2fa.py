"""Give a platform admin an authenticator-app login code (TOTP).

    python manage.py setup_admin_2fa admin@example.com

Prints a QR code to scan with Google Authenticator, Microsoft Authenticator or 1Password.
Running it again replaces the old code, so lost phones can be handled.
"""

import io

import qrcode
from django.core.management.base import BaseCommand, CommandError
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.accounts.models import User


class Command(BaseCommand):
    help = "Set up the authenticator-app code a platform admin needs to log in to the admin."

    def add_arguments(self, parser):
        parser.add_argument("email")

    def handle(self, email, **options):
        user = User.objects.filter(email=email.strip().lower(), is_staff=True).first()
        if user is None:
            raise CommandError(
                "No platform admin with that email. Create one with createsuperuser."
            )
        TOTPDevice.objects.filter(user=user).delete()
        device = TOTPDevice.objects.create(user=user, name="Authenticator app", confirmed=True)
        qr = qrcode.QRCode(border=1)
        qr.add_data(device.config_url)
        out = io.StringIO()
        qr.print_ascii(out=out, invert=True)
        self.stdout.write(out.getvalue())
        self.stdout.write("Scan this with your authenticator app, or add this setup link manually:")
        self.stdout.write(device.config_url)
        self.stdout.write(self.style.SUCCESS(f"Two-step login is on for {user.email}."))
