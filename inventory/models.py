from django.db import models

class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

class Item(TimestampedModel):
    name = models.CharField(max_length=100, unique=True)
    category = models.CharField(max_length=50)
    source = models.CharField(max_length=100, blank=True, null=True)
    quantity = models.PositiveIntegerField(default=1)
    price = models.PositiveIntegerField(default=25000)

    def __str__(self):
        return f"{self.name} (x{self.quantity})"
