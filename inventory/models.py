from django.db import models


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Item(TimestampedModel):
    name = models.CharField(max_length=100, unique=True)
    category = models.CharField(max_length=50)
    sources = models.ManyToManyField("sources.SourceBalance", blank=True, related_name="items")
    quantity = models.PositiveIntegerField(default=1)
    price = models.PositiveIntegerField(blank=True, null=True)
    slug = models.SlugField(max_length=150, blank=True, null=True)

    def save(self, *args, **kwargs):
        if not self.slug and self.name:
            import re
            name = self.name.lower().replace(" ", "_")
            cleaned = re.sub(r"[^a-z0-9_()]", "", name)
            self.slug = re.sub(r"_+", "_", cleaned).strip("_")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} (x{self.quantity})"
