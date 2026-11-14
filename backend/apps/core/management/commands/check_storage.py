"""Check a storage bucket (Cloudflare R2 in staging and production) works the way the app needs.

    python manage.py check_storage --origin https://app.example.com

With no options it checks the configured storage. To try a bucket before it is configured,
pass --endpoint and --bucket; the access key and secret are then asked for and never echoed,
so they stay out of shell history:

    python manage.py check_storage --endpoint https://<account>.r2.cloudflarestorage.com \
        --bucket my-bucket --origin http://localhost:5173

It writes, reads and deletes one small test object under healthcheck/.
"""

import getpass
import secrets
import urllib.error
import urllib.request

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

WEBP_TEST = b"RIFF\x0c\x00\x00\x00WEBPVP8 " + b"\x00" * 16


def _http(method: str, url: str, headers: dict | None = None, data: bytes | None = None):
    request = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read()


class Command(BaseCommand):
    help = "Check the storage bucket: read and write, signed links, privacy, CORS and cleanup rule."

    def add_arguments(self, parser):
        parser.add_argument("--endpoint", help="S3 endpoint; defaults to S3_ENDPOINT_INTERNAL")
        parser.add_argument("--bucket", help="Bucket name; defaults to S3_BUCKET")
        parser.add_argument(
            "--origin",
            action="append",
            default=[],
            help="App address browsers upload from (repeatable), e.g. https://app.example.com",
        )

    def handle(self, *args, **options):
        endpoint = options["endpoint"] or settings.S3_ENDPOINT_INTERNAL
        bucket = options["bucket"] or settings.S3_BUCKET
        if options["endpoint"]:
            # The key ID is not secret, so it is shown as typed; the secret is hidden.
            access_key = input("Access Key ID (32 characters, shown): ").strip()
            if len(access_key) != 32:
                raise CommandError(
                    f"The Access Key ID should be 32 characters; got {len(access_key)}. Run again."
                )
            secret_key = getpass.getpass("Secret Access Key (64 characters, hidden): ").strip()
            if len(secret_key) != 64:
                raise CommandError(
                    f"The Secret Access Key should be 64 characters; got {len(secret_key)}. "
                    "Run again and paste it once."
                )
        else:
            access_key, secret_key = settings.S3_ACCESS_KEY, settings.S3_SECRET_KEY
        client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=settings.S3_REGION,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
        self.failures = 0
        self.stdout.write(f"Checking bucket {bucket} at {endpoint}\n")
        key = f"healthcheck/{secrets.token_hex(6)}.webp"
        upload_key = f"incoming/healthcheck/{secrets.token_hex(6)}.webp"

        try:
            client.put_object(Bucket=bucket, Key=key, Body=WEBP_TEST, ContentType="image/webp")
            body = client.get_object(Bucket=bucket, Key=key)["Body"].read()
            self.result(body == WEBP_TEST, "Server can write and read objects")
        except (ClientError, BotoCoreError) as error:
            self.result(False, "Server can write and read objects", str(error))
            raise CommandError(
                "Stopped: the key, secret, endpoint or bucket name is wrong, or the token "
                "lacks Object Read & Write on this bucket."
            ) from error

        try:
            self.check_links(client, bucket, key, upload_key)
            for origin in options["origin"]:
                self.check_cors(client, bucket, upload_key, origin)
            if not options["origin"]:
                self.warn("CORS not checked: pass --origin with the app's address")
            self.check_lifecycle(client, bucket)
        finally:
            for k in (key, upload_key):
                try:
                    client.delete_object(Bucket=bucket, Key=k)
                except (ClientError, BotoCoreError):
                    self.warn(f"Could not delete test object {k}; delete it by hand")

        if self.failures:
            raise CommandError(f"{self.failures} check(s) failed.")
        self.stdout.write(self.style.SUCCESS("\nStorage is ready for the app."))

    def check_links(self, client, bucket, key, upload_key):
        url = client.generate_presigned_url(
            "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=300
        )
        status, _, body = _http("GET", url)
        self.result(status == 200 and body == WEBP_TEST, "Signed download links work", status)

        unsigned = url.split("?", 1)[0]
        status, _, _ = _http("GET", unsigned)
        self.result(status in (400, 401, 403), "Bucket is private (unsigned links refused)", status)

        url = client.generate_presigned_url(
            "put_object",
            Params={"Bucket": bucket, "Key": upload_key, "ContentType": "image/webp"},
            ExpiresIn=300,
        )
        status, _, _ = _http("PUT", url, {"Content-Type": "image/webp"}, WEBP_TEST)
        self.result(status == 200, "Signed upload links work (as the browser uses them)", status)

    def check_cors(self, client, bucket, upload_key, origin):
        url = client.generate_presigned_url(
            "put_object",
            Params={"Bucket": bucket, "Key": upload_key, "ContentType": "image/webp"},
            ExpiresIn=300,
        )
        status, headers, _ = _http(
            "OPTIONS",
            url,
            {
                "Origin": origin,
                "Access-Control-Request-Method": "PUT",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        allowed = {k.lower(): v for k, v in headers.items()}.get("access-control-allow-origin", "")
        self.result(
            status in (200, 204) and allowed in (origin, "*"),
            f"Browsers at {origin} may upload (CORS)",
            f"status {status}, allowed origin {allowed or 'none'}",
        )

    def check_lifecycle(self, client, bucket):
        try:
            rules = client.get_bucket_lifecycle_configuration(Bucket=bucket).get("Rules", [])
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code", "")
            if code == "NoSuchLifecycleConfiguration":
                self.result(False, "Cleanup rule for incoming/ uploads", "no lifecycle rules")
            else:
                self.warn(
                    f"Cleanup rule not checked ({code}); confirm it in the Cloudflare dashboard"
                )
            return
        found = False
        for rule in rules:
            prefix = rule.get("Filter", {}).get("Prefix", rule.get("Prefix", ""))
            days = rule.get("Expiration", {}).get("Days")
            if rule.get("Status") == "Enabled" and prefix.startswith("incoming") and days:
                found = days <= 7
        self.result(found, "Cleanup rule deletes incoming/ uploads within a week")

    def result(self, ok: bool, label: str, detail=None):
        if ok:
            self.stdout.write(self.style.SUCCESS(f"  ok    {label}"))
        else:
            self.failures += 1
            extra = f" ({detail})" if detail is not None else ""
            self.stdout.write(self.style.ERROR(f"  FAIL  {label}{extra}"))

    def warn(self, label: str):
        self.stdout.write(self.style.WARNING(f"  note  {label}"))
