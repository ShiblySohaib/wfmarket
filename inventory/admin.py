from django.contrib import admin
from .models import Item, SourceBalance

@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'source', 'quantity', 'price', 'created_at')
    list_filter = ('category', 'source')
    search_fields = ('name', 'category', 'source')
    ordering = ('name',)

@admin.register(SourceBalance)
class SourceBalanceAdmin(admin.ModelAdmin):
    list_display = ('source', 'balance')
    search_fields = ('source',)
    ordering = ('source',)
