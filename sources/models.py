from django.db import models

class SourceBalance(models.Model):
    source = models.CharField(max_length=100, unique=True)
    balance = models.PositiveIntegerField(default=0)
    
    def __str__(self):
        return f"{self.source}: {self.balance}"
