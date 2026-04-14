from django.db import models


class SourceBalance(models.Model):
    source_name = models.CharField(max_length=100, unique=True)
    balance = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.source_name}: {self.balance}"

    @property
    def source(self):
        return self.source_name

    @source.setter
    def source(self, value):
        self.source_name = value
