from django.shortcuts import render, get_object_or_404
from django.db.models import Count, Q
from django.utils import timezone
from datetime import timedelta
from tracking.models import Site, Visitor, Contact, Event, ConversionGoal


def dashboard_home(request):
    """Main dashboard overview"""
    # Get overall stats
    total_sites = Site.objects.filter(is_active=True).count()
    total_visitors = Visitor.objects.count()
    total_contacts = Contact.objects.count()
    total_events = Event.objects.count()

    # Get recent sites
    recent_sites = Site.objects.filter(is_active=True)[:5]

    # Get recent contacts
    recent_contacts = Contact.objects.select_related('site', 'visitor')[:10]

    # Get recent events
    recent_events = Event.objects.select_related('site', 'visitor').order_by('-timestamp')[:20]

    # Get event stats by type
    event_stats = Event.objects.values('event_type').annotate(
        count=Count('id')
    ).order_by('-count')

    # Get today's stats
    today = timezone.now().date()
    today_start = timezone.make_aware(timezone.datetime.combine(today, timezone.datetime.min.time()))

    today_visitors = Visitor.objects.filter(first_seen__gte=today_start).count()
    today_events = Event.objects.filter(timestamp__gte=today_start).count()
    today_contacts = Contact.objects.filter(created_at__gte=today_start).count()

    # Get identified vs anonymous visitor stats
    identified_visitors = Visitor.objects.filter(is_identified=True).count()
    anonymous_visitors = total_visitors - identified_visitors

    # Get events over time (last 7 days)
    end_date = timezone.now()
    daily_event_data = []
    for i in range(7):
        day = end_date - timedelta(days=6-i)  # Start from 6 days ago
        day_start = timezone.make_aware(timezone.datetime.combine(day.date(), timezone.datetime.min.time()))
        day_end = day_start + timedelta(days=1)

        count = Event.objects.filter(
            timestamp__gte=day_start,
            timestamp__lt=day_end
        ).count()

        daily_event_data.append({
            'date': day.strftime('%b %d'),
            'count': count
        })

    # Prepare chart data for template
    import json

    # Event type chart data
    event_type_labels = [stat['event_type'] for stat in event_stats]
    event_type_counts = [stat['count'] for stat in event_stats]

    # Daily events chart data
    daily_event_labels = [day['date'] for day in daily_event_data]
    daily_event_counts = [day['count'] for day in daily_event_data]

    context = {
        'total_sites': total_sites,
        'total_visitors': total_visitors,
        'total_contacts': total_contacts,
        'total_events': total_events,
        'recent_sites': recent_sites,
        'recent_contacts': recent_contacts,
        'recent_events': recent_events,
        'event_stats': event_stats,
        'today_visitors': today_visitors,
        'today_events': today_events,
        'today_contacts': today_contacts,
        'identified_visitors': identified_visitors,
        'anonymous_visitors': anonymous_visitors,
        # Chart data (JSON for JavaScript)
        'event_type_labels_json': json.dumps(event_type_labels),
        'event_type_counts_json': json.dumps(event_type_counts),
        'daily_event_labels_json': json.dumps(daily_event_labels),
        'daily_event_counts_json': json.dumps(daily_event_counts),
    }

    return render(request, 'dashboard/home.html', context)


def site_list(request):
    """List all sites"""
    sites = Site.objects.annotate(
        visitor_count=Count('visitors'),
        contact_count=Count('contacts'),
        event_count=Count('events'),
    )

    context = {
        'sites': sites,
    }

    return render(request, 'dashboard/site_list.html', context)


def site_detail(request, site_id):
    """Detailed view of a single site"""
    site = get_object_or_404(Site, id=site_id)

    # Date range for analytics (last 30 days)
    end_date = timezone.now()
    start_date = end_date - timedelta(days=30)

    # Get visitor stats
    total_visitors = site.visitors.count()
    identified_visitors = site.visitors.filter(is_identified=True).count()
    anonymous_visitors = total_visitors - identified_visitors

    # Get contact stats
    total_contacts = site.contacts.count()

    # Get event stats
    total_events = site.events.count()
    event_breakdown = site.events.values('event_type').annotate(
        count=Count('id')
    ).order_by('-count')

    # Recent events
    recent_events = site.events.select_related('visitor').order_by('-timestamp')[:20]

    # Recent contacts
    recent_contacts = site.contacts.select_related('visitor')[:10]

    # Daily event trend (last 7 days)
    daily_events = []
    for i in range(7):
        day = end_date - timedelta(days=i)
        day_start = timezone.make_aware(timezone.datetime.combine(day.date(), timezone.datetime.min.time()))
        day_end = day_start + timedelta(days=1)

        count = site.events.filter(
            timestamp__gte=day_start,
            timestamp__lt=day_end
        ).count()

        daily_events.append({
            'date': day.strftime('%Y-%m-%d'),
            'count': count
        })

    daily_events.reverse()

    context = {
        'site': site,
        'total_visitors': total_visitors,
        'identified_visitors': identified_visitors,
        'anonymous_visitors': anonymous_visitors,
        'total_contacts': total_contacts,
        'total_events': total_events,
        'event_breakdown': event_breakdown,
        'recent_events': recent_events,
        'recent_contacts': recent_contacts,
        'daily_events': daily_events,
    }

    return render(request, 'dashboard/site_detail.html', context)


def contact_list(request):
    """List all contacts"""
    site_id = request.GET.get('site')

    contacts = Contact.objects.select_related('site', 'visitor')

    if site_id:
        contacts = contacts.filter(site_id=site_id)

    contacts = contacts.annotate(
        event_count=Count('visitor__events')
    )

    sites = Site.objects.filter(is_active=True)

    context = {
        'contacts': contacts,
        'sites': sites,
        'selected_site': site_id,
    }

    return render(request, 'dashboard/contact_list.html', context)


def contact_detail(request, contact_id):
    """Detailed view of a single contact"""
    contact = get_object_or_404(Contact.objects.select_related('site', 'visitor'), id=contact_id)

    # Get all events for this contact's visitor
    if contact.visitor:
        events = contact.visitor.events.all()[:50]
        event_count = contact.visitor.events.count()
    else:
        events = []
        event_count = 0

    context = {
        'contact': contact,
        'events': events,
        'event_count': event_count,
    }

    return render(request, 'dashboard/contact_detail.html', context)


def visitor_detail(request, visitor_id):
    """Detailed view of a single visitor"""
    visitor = get_object_or_404(
        Visitor.objects.select_related('site', 'contact'),
        id=visitor_id
    )

    # Get events
    events = visitor.events.all()[:50]
    event_count = visitor.events.count()

    # Get contact if identified
    contact = None
    if visitor.is_identified:
        try:
            contact = visitor.contact
        except Contact.DoesNotExist:
            # If visitor is marked as identified but has no contact, this is a data issue
            # Auto-fix: Try to find and create the missing contact
            from tracking.models import Event, EnrichmentData

            # Try to find contact by visitor FK first
            contact = Contact.objects.filter(visitor=visitor).first()

            # If still no contact, try to recreate from identify event
            if not contact:
                identify_event = Event.objects.filter(
                    visitor=visitor,
                    event_type='custom',
                    event_data__event_name='identify'
                ).order_by('-timestamp').first()

                if identify_event:
                    identity_data = identify_event.event_data.get('identity_data', {})
                    email = identity_data.get('email')

                    if email:
                        name = identity_data.get('name', '')
                        phone = identity_data.get('phone', '')

                        # Get or create enrichment
                        enrichment, _ = EnrichmentData.objects.get_or_create(
                            site=visitor.site,
                            email=email,
                            defaults={
                                'first_name': name.split()[0] if name else '',
                                'last_name': ' '.join(name.split()[1:]) if name and len(name.split()) > 1 else '',
                                'phone': phone,
                                'source': 'visitor_identification'
                            }
                        )

                        # Create contact
                        contact, created = Contact.objects.get_or_create(
                            site=visitor.site,
                            email=email,
                            defaults={
                                'visitor': visitor,
                                'enrichment_data': enrichment,
                                'name': name,
                                'phone': phone,
                            }
                        )

                        if not created and contact.visitor != visitor:
                            contact.visitor = visitor
                            contact.save()

                        # Store fingerprint data in enrichment
                        if visitor.browser_name and visitor.os_name:
                            updated = False
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
                                updated = True
                            if visitor.user_agent and visitor.user_agent not in enrichment.user_agents:
                                enrichment.user_agents.append(visitor.user_agent)
                                updated = True
                            if visitor.ip_address and visitor.ip_address not in enrichment.ip_addresses:
                                enrichment.ip_addresses.append(visitor.ip_address)
                                updated = True
                            if phone and phone not in enrichment.phone_numbers:
                                enrichment.phone_numbers.append(phone)
                                updated = True
                            if updated:
                                enrichment.save()

    context = {
        'visitor': visitor,
        'events': events,
        'event_count': event_count,
        'contact': contact,
    }

    return render(request, 'dashboard/visitor_detail.html', context)


def demo_page(request):
    """Serve the demo e-commerce website"""
    # Get a sample site key for the demo (first active site)
    sample_site = Site.objects.filter(is_active=True).first()
    site_key = sample_site.site_key if sample_site else 'YOUR_SITE_KEY'

    context = {
        'site_key': site_key,
        'has_site': sample_site is not None,
    }

    return render(request, 'dashboard/demo.html', context)
