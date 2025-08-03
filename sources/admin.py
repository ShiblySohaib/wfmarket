from django.contrib import admin
from .models import SourceBalance

@admin.register(SourceBalance)
class SourceBalanceAdmin(admin.ModelAdmin):
    list_display = ('source', 'balance')
    search_fields = ('source',)
    ordering = ('source',)
