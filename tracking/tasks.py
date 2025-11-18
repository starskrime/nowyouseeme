from celery import shared_task
from django.db import transaction
from .models import Visitor, Contact


def process_identity_resolution_sync(visitor_id, identity_data):
    """
    Synchronous identity resolution function
    Associates a visitor with an email and creates/updates a Contact
    Also checks enrichment data for matching email
    """
    try:
        visitor = Visitor.objects.get(id=visitor_id)
    except Visitor.DoesNotExist:
        return

    email = identity_data.get('email')
    if not email:
        return

    with transaction.atomic():
        # Check if we have enrichment data for this email
        from .models import EnrichmentData
        enrichment = None
        try:
            enrichment = EnrichmentData.objects.get(site=visitor.site, email=email)
        except EnrichmentData.DoesNotExist:
            pass

        # Collect all visitor information for comprehensive contact data
        from django.utils import timezone
        visitor_info = {
            # Browser fingerprint data
            'browser_fingerprint': {
                'browser_name': visitor.browser_name,
                'browser_version': visitor.browser_version,
                'os_name': visitor.os_name,
                'device_type': visitor.device_type,
                'screen_resolution': visitor.screen_resolution,
                'timezone': visitor.timezone,
                'language': visitor.language,
            },
            # Tracking data
            'ip_address': visitor.ip_address,
            'user_agent': visitor.user_agent,
            'referrer': visitor.referrer,
            # UTM attribution data (first-touch)
            'utm_data': {
                'utm_source': visitor.utm_source,
                'utm_medium': visitor.utm_medium,
                'utm_campaign': visitor.utm_campaign,
                'utm_term': visitor.utm_term,
                'utm_content': visitor.utm_content,
            },
            # Identification metadata
            'matched_via': 'email',
            'first_seen': visitor.first_seen.isoformat() if visitor.first_seen else None,
            'identified_at': timezone.now().isoformat(),
        }

        # Prepare contact defaults
        defaults = {
            'visitor': visitor,
            'name': identity_data.get('name', ''),
            'phone': identity_data.get('phone', ''),
            'extra_data': {
                **{k: v for k, v in identity_data.items() if k not in ['email', 'name', 'phone']},
                **visitor_info,  # Include all visitor information
            }
        }

        # If we have enrichment data, use it to populate contact fields
        if enrichment:
            defaults['enrichment_data'] = enrichment
            defaults['name'] = f"{enrichment.first_name} {enrichment.last_name}".strip() or defaults['name']
            defaults['phone'] = enrichment.phone or defaults['phone']
            defaults['linkedin_url'] = enrichment.linkedin_url
            defaults['facebook_url'] = enrichment.facebook_url
            defaults['extra_data'].update({
                'company': enrichment.company,
                'job_title': enrichment.job_title,
                'location': enrichment.location,
            })

        # Check if visitor already has a contact
        try:
            existing_contact = visitor.contact
            # Visitor already has a contact, update it with new email/data
            contact = existing_contact
            created = False
            updated = False
            # Update email if it changed
            if contact.email != email:
                contact.email = email
                updated = True
            # Update other fields from identity_data
            if identity_data.get('name'):
                contact.name = identity_data.get('name')
                updated = True
            if identity_data.get('phone'):
                contact.phone = identity_data.get('phone')
                updated = True
            # Update enrichment data if we found matching enrichment
            if enrichment and contact.enrichment_data != enrichment:
                contact.enrichment_data = enrichment
                contact.name = f"{enrichment.first_name} {enrichment.last_name}".strip() or contact.name
                contact.phone = enrichment.phone or contact.phone
                contact.linkedin_url = enrichment.linkedin_url
                contact.facebook_url = enrichment.facebook_url
                updated = True
            # Update extra_data with latest visitor information
            if not contact.extra_data:
                contact.extra_data = {}
            contact.extra_data.update(visitor_info)
            updated = True
            if updated:
                contact.save()
        except Contact.DoesNotExist:
            # Visitor doesn't have a contact yet, create or get one
            contact, created = Contact.objects.get_or_create(
                site=visitor.site,
                email=email,
                defaults=defaults
            )

            # If contact already exists but linked to different visitor, update it
            if not created and contact.visitor != visitor:
                # Optionally merge visitors here if you want
                contact.visitor = visitor
                contact.save()

        # Update contact data if provided
        if not created:
            updated = False
            if 'name' in identity_data and identity_data['name']:
                contact.name = identity_data['name']
                updated = True
            if 'phone' in identity_data and identity_data['phone']:
                contact.phone = identity_data['phone']
                updated = True

            # Merge extra data
            if not contact.extra_data:
                contact.extra_data = {}
            for k, v in identity_data.items():
                if k not in ['email', 'name', 'phone'] and v:
                    contact.extra_data[k] = v
                    updated = True

            # Update visitor information
            contact.extra_data.update(visitor_info)
            updated = True

            if updated:
                contact.save()

        # Mark visitor as identified
        visitor.is_identified = True
        visitor.matched_via = 'email'
        visitor.save()

        # Store visitor's browser fingerprint, IP, and phone in enrichment data for future matching
        # Create enrichment data if it doesn't exist
        if not enrichment:
            from .models import EnrichmentData
            enrichment, created = EnrichmentData.objects.get_or_create(
                site=visitor.site,
                email=email,
                defaults={
                    'first_name': identity_data.get('name', '').split()[0] if identity_data.get('name') else '',
                    'last_name': ' '.join(identity_data.get('name', '').split()[1:]) if identity_data.get('name') and len(identity_data.get('name', '').split()) > 1 else '',
                    'phone': identity_data.get('phone', ''),
                    'source': 'visitor_identification'
                }
            )
            # Link enrichment to contact
            if contact and not contact.enrichment_data:
                contact.enrichment_data = enrichment
                contact.save()

        if enrichment:
            updated_enrichment = False

            # Store browser fingerprint
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
                    updated_enrichment = True

            # Store user agent
            if visitor.user_agent and visitor.user_agent not in enrichment.user_agents:
                enrichment.user_agents.append(visitor.user_agent)
                updated_enrichment = True

            # Store IP address
            if visitor.ip_address and visitor.ip_address not in enrichment.ip_addresses:
                enrichment.ip_addresses.append(visitor.ip_address)
                updated_enrichment = True

            # Store phone number from identity data
            if identity_data.get('phone'):
                phone = identity_data.get('phone')
                if phone not in enrichment.phone_numbers:
                    enrichment.phone_numbers.append(phone)
                    updated_enrichment = True

            if updated_enrichment:
                enrichment.save()

        return str(contact.id)


@shared_task(bind=True, max_retries=3)
def process_identity_resolution(self, visitor_id, identity_data):
    """
    Celery task for identity resolution
    This runs asynchronously when Celery is available
    """
    try:
        return process_identity_resolution_sync(visitor_id, identity_data)
    except Exception as exc:
        # Retry on failure
        raise self.retry(exc=exc, countdown=60)
