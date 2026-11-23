"""Admin login with an authenticator-app code in one step.

django-otp asks the user to pick a device before it checks a code, so the first login attempt
always fails with "Please select a device." (the list only fills in after the password is
checked). Admins here have one authenticator app each, so when there is exactly one confirmed
device it is used without asking. With several, the user still picks one, as django-otp intends:
we never try a code against more than one device.
"""

from django_otp.admin import OTPAdminAuthenticationForm
from django_otp.plugins.otp_totp.models import TOTPDevice


class OneStepOTPAdminAuthenticationForm(OTPAdminAuthenticationForm):
    def _chosen_device(self, user):
        device = super()._chosen_device(user)
        if device is None:
            devices = list(TOTPDevice.objects.filter(user=user, confirmed=True)[:2])
            if len(devices) == 1:
                device = devices[0]
        return device
