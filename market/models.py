from django.db import models

class MarketSettings(models.Model):
    """Persistent settings for the market fetcher shown in the admin UI."""

    auto_refresh_interval = models.IntegerField(default=120, help_text="Seconds between automatic fetches")
    high_alert_threshold = models.IntegerField(default=11)
    alert_threshold = models.IntegerField(default=8)
    rate_limit = models.IntegerField(default=3, help_text="Max concurrent requests / per-second window")
    max_orders = models.IntegerField(
        null=True,
        blank=True,
        default=10,
        help_text="Max orders to show per item; blank for no limit",
    )

    class Meta:
        verbose_name = "Market Settings"
        verbose_name_plural = "Market Settings"

    def __str__(self):
        return "Market Settings"
