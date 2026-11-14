from django.core.mail import send_mail
from procrastinate.contrib.django import app


@app.task(name="notifications.send_email", retry=5)
def send_email(to: str, subject: str, body: str) -> None:
    """Send one plain-text email. Retried with backoff if the mail service is down."""
    send_mail(subject, body, None, [to])
