from botocore.exceptions import ClientError
from django.conf import settings
from django.core.management.base import BaseCommand

from apps.core.storage import internal_client


class Command(BaseCommand):
    help = "Create the storage bucket if it does not exist (local development only)."

    def handle(self, *args, **options):
        client = internal_client()
        try:
            client.head_bucket(Bucket=settings.S3_BUCKET)
            self.stdout.write(f"Bucket {settings.S3_BUCKET} exists.")
        except ClientError:
            client.create_bucket(Bucket=settings.S3_BUCKET)
            self.stdout.write(self.style.SUCCESS(f"Created bucket {settings.S3_BUCKET}."))
