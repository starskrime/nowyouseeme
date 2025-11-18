from django.core.management.base import BaseCommand
from tracking.models import Visitor, Contact, EnrichmentData, Site


class Command(BaseCommand):
    help = 'Retroactively identify unidentified visitors based on enrichment data'

    def add_arguments(self, parser):
        parser.add_argument(
            '--site',
            type=str,
            help='Site ID or site key to process (optional, processes all sites if not specified)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be identified without actually making changes',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        site_filter = options.get('site')

        # Get sites to process
        if site_filter:
            try:
                sites = Site.objects.filter(site_key=site_filter) | Site.objects.filter(id=site_filter)
                if not sites.exists():
                    self.stdout.write(self.style.ERROR(f'Site not found: {site_filter}'))
                    return
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Error finding site: {e}'))
                return
        else:
            sites = Site.objects.filter(is_active=True)

        total_identified = 0
        total_processed = 0

        for site in sites:
            self.stdout.write(f'\nProcessing site: {site.name} ({site.site_key})')
            self.stdout.write('=' * 80)

            # Get unidentified visitors for this site
            unidentified_visitors = Visitor.objects.filter(
                site=site,
                is_identified=False
            )

            self.stdout.write(f'Found {unidentified_visitors.count()} unidentified visitors')

            # Get all enrichment data for this site
            enrichment_data = EnrichmentData.objects.filter(site=site)
            self.stdout.write(f'Found {enrichment_data.count()} enrichment records to match against\n')

            for visitor in unidentified_visitors:
                total_processed += 1
                enrichment = None
                matched_via = None
                match_details = {}

                # Priority 1: Browser fingerprint matching
                if visitor.browser_name and visitor.os_name:
                    for enrich in enrichment_data:
                        for stored_fp in enrich.browser_fingerprints:
                            if (stored_fp.get('browser_name') == visitor.browser_name and
                                stored_fp.get('os_name') == visitor.os_name and
                                stored_fp.get('device_type') == visitor.device_type and
                                stored_fp.get('screen_resolution') == visitor.screen_resolution):
                                enrichment = enrich
                                matched_via = 'browser_fingerprint'
                                match_details = {
                                    'browser': visitor.browser_name,
                                    'os': visitor.os_name,
                                    'device': visitor.device_type,
                                    'resolution': visitor.screen_resolution
                                }
                                break
                        if enrichment:
                            break

                # Priority 2: User agent matching
                if not enrichment and visitor.user_agent:
                    for enrich in enrichment_data:
                        if visitor.user_agent in enrich.user_agents:
                            enrichment = enrich
                            matched_via = 'user_agent'
                            match_details = {'user_agent': visitor.user_agent}
                            break

                # Priority 3: IP address matching
                if not enrichment and visitor.ip_address:
                    for enrich in enrichment_data:
                        if visitor.ip_address in enrich.ip_addresses:
                            enrichment = enrich
                            matched_via = 'ip_address'
                            match_details = {'ip': visitor.ip_address}
                            break

                # If we found a match, create/update contact
                if enrichment:
                    total_identified += 1

                    if dry_run:
                        self.stdout.write(
                            self.style.SUCCESS(
                                f'[DRY RUN] Would identify visitor {visitor.visitor_id[:20]}... '
                                f'as {enrichment.email} via {matched_via}'
                            )
                        )
                    else:
                        try:
                            # Create or get contact
                            contact, contact_created = Contact.objects.get_or_create(
                                site=site,
                                email=enrichment.email,
                                defaults={
                                    'visitor': visitor,
                                    'enrichment_data': enrichment,
                                    'name': f"{enrichment.first_name} {enrichment.last_name}".strip(),
                                    'phone': enrichment.phone,
                                    'linkedin_url': enrichment.linkedin_url,
                                    'facebook_url': enrichment.facebook_url,
                                    'extra_data': {
                                        'company': enrichment.company,
                                        'job_title': enrichment.job_title,
                                        'location': enrichment.location,
                                        'matched_via': matched_via,
                                        'match_details': match_details,
                                    }
                                }
                            )

                            # If contact exists but linked to different visitor, update it
                            if not contact_created and contact.visitor != visitor:
                                contact.visitor = visitor
                                contact.save()

                            # Mark visitor as identified
                            visitor.is_identified = True
                            visitor.matched_via = matched_via
                            visitor.save()

                            # Store this visitor's fingerprint for future matching
                            if visitor.browser_name and visitor.os_name:
                                fp_dict = {
                                    'browser_name': visitor.browser_name,
                                    'os_name': visitor.os_name,
                                    'device_type': visitor.device_type,
                                    'screen_resolution': visitor.screen_resolution,
                                    'timezone': visitor.timezone,
                                    'language': visitor.language
                                }
                                if fp_dict not in enrichment.browser_fingerprints:
                                    enrichment.browser_fingerprints.append(fp_dict)

                                # Store user agent if not already stored
                                if visitor.user_agent and visitor.user_agent not in enrichment.user_agents:
                                    enrichment.user_agents.append(visitor.user_agent)

                                # Store IP if not already stored
                                if visitor.ip_address and visitor.ip_address not in enrichment.ip_addresses:
                                    enrichment.ip_addresses.append(visitor.ip_address)

                                enrichment.save()

                            action = 'Created' if contact_created else 'Updated'
                            self.stdout.write(
                                self.style.SUCCESS(
                                    f'{action} contact for visitor {visitor.visitor_id[:20]}... '
                                    f'-> {enrichment.email} (matched via {matched_via})'
                                )
                            )
                        except Exception as e:
                            self.stdout.write(
                                self.style.ERROR(
                                    f'Error identifying visitor {visitor.visitor_id}: {e}'
                                )
                            )

        self.stdout.write('\n' + '=' * 80)
        self.stdout.write(self.style.SUCCESS(f'\nSummary:'))
        self.stdout.write(f'  Total visitors processed: {total_processed}')
        self.stdout.write(f'  Visitors identified: {total_identified}')

        if dry_run:
            self.stdout.write(self.style.WARNING('\nThis was a DRY RUN. No changes were made.'))
            self.stdout.write('Run without --dry-run to actually identify visitors.')
        else:
            self.stdout.write(self.style.SUCCESS('\nIdentification complete!'))
