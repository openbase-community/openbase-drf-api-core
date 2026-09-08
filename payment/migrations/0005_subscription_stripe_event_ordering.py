from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("payment", "0004_alter_subscription_platform_data"),
    ]

    operations = [
        migrations.AddField(
            model_name="subscription",
            name="stripe_event_created",
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="subscription",
            name="stripe_event_id",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="subscription",
            name="stripe_event_terminal",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="subscription",
            name="stripe_terminal_cleanup_completed",
            field=models.BooleanField(default=False),
        ),
    ]
