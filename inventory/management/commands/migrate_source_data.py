# Generated data migration script

from django.core.management.base import BaseCommand
from django.db import connection

class Command(BaseCommand):
    help = 'Migrate source balance data from inventory to sources app'

    def handle(self, *args, **options):
        cursor = connection.cursor()
        
        # Copy data from inventory_sourcebalance to sources_sourcebalance
        cursor.execute("""
            INSERT INTO sources_sourcebalance (source, balance)
            SELECT source, balance FROM inventory_sourcebalance
        """)
        
        rows_copied = cursor.rowcount
        self.stdout.write(
            self.style.SUCCESS(f'Successfully copied {rows_copied} source balance records')
        )
