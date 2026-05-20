from django.contrib.sites.models import Site
from django.db import models


class SiteAttributes(models.Model):
    site = models.OneToOneField(
        Site,
        on_delete=models.CASCADE,
        related_name="attributes",
    )
    admin_app_labels = models.JSONField(
        default=list,
        blank=True,
        help_text="Django admin app labels visible for this site. Leave empty to show all apps.",
    )
    s3_frontend_folder = models.CharField(
        max_length=255,
        blank=True,
        help_text="The S3 folder where frontend assets are stored",
    )
    stripe_product_id = models.CharField(
        max_length=255,
        blank=True,
        default="prod_implementme",
        help_text="The Stripe Product ID for this site",
    )
    stripe_price_cents = models.IntegerField(
        default=2000,
        help_text="The price in cents for the Stripe subscription",
    )
    from_email = models.EmailField(
        default="team@my-app.openbase.app",
        help_text="Default from email address for this site",
    )

    class Meta:
        verbose_name_plural = "Site attributes"

    def __str__(self):
        return f"Attributes for {self.site.name}"
