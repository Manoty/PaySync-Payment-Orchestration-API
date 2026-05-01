from django.core.management.base import BaseCommand
from authentication.models import APIClient


class Command(BaseCommand):
    help = "Manage PaySync API clients (create, list, revoke)"

    def add_arguments(self, parser):
        subparsers = parser.add_subparsers(dest='action')

        # Create
        create = subparsers.add_parser('create', help='Create a new API client')
        create.add_argument('--name',          required=True)
        create.add_argument('--source-system', required=True)
        create.add_argument('--rate-limit',    type=int, default=30)

        # List
        subparsers.add_parser('list', help='List all API clients')

        # Revoke
        revoke = subparsers.add_parser('revoke', help='Revoke an API client')
        revoke.add_argument('--source-system', required=True)

    def handle(self, *args, **options):
        action = options.get('action')

        if action == 'create':
            self._create_client(options)
        elif action == 'list':
            self._list_clients()
        elif action == 'revoke':
            self._revoke_client(options)
        else:
            self.stdout.write("Usage: manage_api_clients create|list|revoke")

    def _create_client(self, options):
        name          = options['name']
        source_system = options['source_system']
        rate_limit    = options['rate_limit']

        if APIClient.objects.filter(source_system=source_system).exists():
            self.stderr.write(
                f"Client for '{source_system}' already exists. "
                f"Revoke it first before creating a new one."
            )
            return

        client, raw_key = APIClient.create_with_key(
            name=name,
            source_system=source_system,
            rate_limit_per_minute=rate_limit,
        )

        self.stdout.write(self.style.SUCCESS(
            f"\n{'='*60}\n"
            f"API Client Created Successfully\n"
            f"{'='*60}\n"
            f"Name:          {client.name}\n"
            f"Source System: {client.source_system}\n"
            f"Rate Limit:    {client.rate_limit_per_minute} req/min\n"
            f"Status:        {client.status}\n"
            f"\n⚠️  API KEY (shown ONCE — store it securely):\n\n"
            f"    {raw_key}\n\n"
            f"Include this in requests as:\n"
            f"    X-API-Key: {raw_key}\n"
            f"{'='*60}\n"
        ))

    def _list_clients(self):
        clients = APIClient.objects.all()
        if not clients:
            self.stdout.write("No API clients registered.")
            return

        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(f"{'Name':<25} {'System':<12} {'Status':<12} {'Last Used'}")
        self.stdout.write(f"{'='*60}")
        for c in clients:
            last_used = c.last_used_at.strftime('%Y-%m-%d %H:%M') if c.last_used_at else 'Never'
            self.stdout.write(
                f"{c.name:<25} {c.source_system:<12} {c.status:<12} {last_used}"
            )

    def _revoke_client(self, options):
        try:
            client = APIClient.objects.get(source_system=options['source_system'])
            client.status = APIClient.Status.REVOKED
            client.save()
            self.stdout.write(
                self.style.WARNING(f"Client '{client.name}' revoked successfully.")
            )
        except APIClient.DoesNotExist:
            self.stderr.write(f"No client found for source_system='{options['source_system']}'")