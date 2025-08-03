from django.core.management.base import BaseCommand
from sources.models import SourceBalance

class Command(BaseCommand):
    help = 'Load dummy source balance data'

    def handle(self, *args, **options):
        # Clear existing data
        SourceBalance.objects.all().delete()
        
        # Create dummy source balances
        sources = [
            {'source': 'red veil', 'balance': 50000},
        ]
        
        created_count = 0
        for source_data in sources:
            source_balance, created = SourceBalance.objects.get_or_create(
                source=source_data['source'],
                defaults={'balance': source_data['balance']}
            )
            if created:
                created_count += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f'Created source balance: {source_balance.source} - {source_balance.balance}'
                    )
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f'Source balance already exists: {source_balance.source} - {source_balance.balance}'
                    )
                )
        
        self.stdout.write(
            self.style.SUCCESS(f'Successfully loaded {created_count} source balances!')
        )
