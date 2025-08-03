from django.contrib import admin
from .models import Item

@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'source', 'quantity', 'price', 'created_at')
    list_filter = ('category', 'source')
    search_fields = ('name', 'category', 'source')
    ordering = ('name',)
