from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("studios", "0002_branding")]

    operations = [
        migrations.AddField(
            model_name="studio",
            name="phone",
            field=models.CharField(
                blank=True, help_text="WhatsApp number, country code and digits only.", max_length=16
            ),
        ),
        migrations.AddField(
            model_name="studio", name="contact_email", field=models.EmailField(blank=True, max_length=254)
        ),
        migrations.AddField(
            model_name="studio", name="address", field=models.CharField(blank=True, max_length=300)
        ),
        migrations.AddField(
            model_name="studio", name="city", field=models.CharField(blank=True, max_length=100)
        ),
        migrations.AddField(
            model_name="studio", name="website", field=models.URLField(blank=True, max_length=200)
        ),
        migrations.AddField(
            model_name="studio",
            name="instagram",
            field=models.CharField(blank=True, help_text="Handle without the @.", max_length=30),
        ),
    ]
