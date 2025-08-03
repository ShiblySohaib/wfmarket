import json
import os
from django.core.management.base import BaseCommand
from inventory.models import Item


class Command(BaseCommand):
    help = 'Load items from data.json into the database'

    def handle(self, *args, **options):
        # Get the path to data.json
        data_file = os.path.join('inventory', 'data.json')
        
        if not os.path.exists(data_file):
            self.stdout.write(
                self.style.ERROR(f'File {data_file} not found')
            )
            return
        
        # Load the JSON data
        with open(data_file, 'r') as f:
            item_names = json.load(f)
        
        # Common values for all items
        common_data = {
            'category': 'mods',
            'source': 'red veil',
            'quantity': 1,
            'price': 25000,
        }
        
        created_count = 0
        updated_count = 0
        
        for item_name in item_names:
            item, created = Item.objects.get_or_create(
                name=item_name,
                defaults=common_data
            )
            
            if created:
                created_count += 1
                self.stdout.write(f'Created: {item_name}')
            else:
                updated_count += 1
                self.stdout.write(f'Already exists: {item_name}')
        
        self.stdout.write(
            self.style.SUCCESS(
                f'Successfully processed {len(item_names)} items. '
                f'Created: {created_count}, Already existed: {updated_count}'
            )
        )
