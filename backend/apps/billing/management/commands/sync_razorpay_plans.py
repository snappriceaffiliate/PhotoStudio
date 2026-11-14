from django.core.management.base import BaseCommand, CommandError

from apps.billing import razorpay
from apps.billing.models import Plan


class Command(BaseCommand):
    help = (
        "Create a Razorpay plan for every public plan that has none yet (run once per environment)."
    )

    def handle(self, *args, **options):
        if not razorpay.configured():
            raise CommandError("Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET first.")
        for plan in Plan.objects.filter(is_public=True, razorpay_plan_id=""):
            plan.razorpay_plan_id = razorpay.create_plan(plan.name, plan.price_paise)
            plan.save(update_fields=["razorpay_plan_id"])
            self.stdout.write(f"{plan.name}: {plan.razorpay_plan_id}")
        self.stdout.write(self.style.SUCCESS("Plans are in sync."))
