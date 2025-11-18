from django.shortcuts import render
from rest_framework import viewsets, status
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from .models import Site, Visitor, Contact, Event, ConversionGoal, APIKey
from .serializers import (
    TrackEventSerializer, SiteSerializer, VisitorSerializer,
    ContactSerializer, EventSerializer, ConversionGoalSerializer
)
from .tasks import process_identity_resolution
from .authentication import APIKeyAuthentication
from .permissions import HasAPIKeyOrIsStaff, IsAPISiteOwner


def get_client_ip(request):
    """Extract client IP from request"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


@csrf_exempt
@api_view(['POST'])
@permission_classes([AllowAny])
def track_event(request):
    """
    Main endpoint for receiving tracking events from the pixel

    IMPORTANT: Visitor identification is ALWAYS determined server-side.
    The client cannot send is_identified or matched_via - these fields are
    computed by the server based on multi-factor matching logic.
    """
    # Log incoming request data to verify client is not sending identification fields
    import logging
    logger = logging.getLogger(__name__)
    if 'is_identified' in request.data or 'matched_via' in request.data:
        logger.warning(f"CLIENT ATTEMPTED TO SEND IDENTIFICATION FIELDS: {request.data}")
        # These fields will be ignored by the serializer, but we log the attempt

    serializer = TrackEventSerializer(data=request.data)

    if not serializer.is_valid():
        return Response(
            {'error': 'Invalid data', 'details': serializer.errors},
            status=status.HTTP_400_BAD_REQUEST
        )

    data = serializer.validated_data

    try:
        # Get the site
        site = Site.objects.get(site_key=data['site_key'], is_active=True)

        # Extract browser fingerprint from request (sent at top level by pixel.js)
        browser_fp = data.get('browser_fingerprint', {})

        # Extract UTM parameters (stored for first-touch attribution)
        stored_utm = data.get('stored_utm_params', {})

        # Get or create visitor
        ip_address = get_client_ip(request)
        visitor, created = Visitor.objects.get_or_create(
            site=site,
            visitor_id=data['visitor_id'],
            defaults={
                'user_agent': request.META.get('HTTP_USER_AGENT', ''),
                'ip_address': ip_address,
                'referrer': data.get('referrer', ''),
                'browser_name': browser_fp.get('browser_name'),
                'os_name': browser_fp.get('os_name'),
                'device_type': browser_fp.get('device_type'),
                'screen_resolution': browser_fp.get('screen_resolution'),
                'timezone': browser_fp.get('timezone'),
                'language': browser_fp.get('language'),
                # First-touch UTM attribution
                'utm_source': stored_utm.get('utm_source'),
                'utm_medium': stored_utm.get('utm_medium'),
                'utm_campaign': stored_utm.get('utm_campaign'),
                'utm_term': stored_utm.get('utm_term'),
                'utm_content': stored_utm.get('utm_content'),
            }
        )

        # Update visitor data if not newly created
        if not created:
            # Update fingerprint if provided
            if browser_fp:
                visitor.browser_name = browser_fp.get('browser_name') or visitor.browser_name
                visitor.os_name = browser_fp.get('os_name') or visitor.os_name
                visitor.device_type = browser_fp.get('device_type') or visitor.device_type
                visitor.screen_resolution = browser_fp.get('screen_resolution') or visitor.screen_resolution
                visitor.timezone = browser_fp.get('timezone') or visitor.timezone
                visitor.language = browser_fp.get('language') or visitor.language
            visitor.save()

        # SIMPLIFIED MATCHING: Only match against CSV enrichment data
        # Match incoming event data against enrichment data from CSV uploads ONLY
        from .models import EnrichmentData, Contact

        try:
            enrichment = None
            matched_via = None
            match_details = {}

            # Only try to match if visitor is NOT already identified
            # This ensures we preserve the ORIGINAL matching method
            if not visitor.is_identified:
                # Get all enrichment data for this site
                all_enrichment = EnrichmentData.objects.filter(site=site)

                # Try to match by IP address ONLY
                # This is the most reliable method as it comes from CSV
                if ip_address:
                    for enrichment_data in all_enrichment:
                        if ip_address in enrichment_data.ip_addresses:
                            enrichment = enrichment_data
                            matched_via = 'ip_address'
                            match_details = {'ip': ip_address}
                            break

                # If matched, create contact and mark visitor as identified
                if enrichment:
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

                    # Mark visitor as identified - ONLY SET ONCE
                    visitor.is_identified = True
                    visitor.matched_via = matched_via
                    visitor.save()

        except Exception as e:
            # Log error but don't fail the request
            import traceback
            print(f"Auto-matching error: {e}")
            print(traceback.format_exc())

        # Extract current UTM parameters for last-touch attribution
        current_utm = data.get('utm_params', {})

        # Create event
        event = Event.objects.create(
            site=site,
            visitor=visitor,
            event_type=data['event_type'],
            event_name=data.get('event_name', ''),
            page_url=data['page_url'],
            page_title=data.get('page_title', ''),
            event_data=data.get('event_data', {}),
            session_id=data.get('session_id', ''),
            referrer=data.get('referrer', ''),
            # Last-touch UTM attribution
            utm_source=current_utm.get('utm_source'),
            utm_medium=current_utm.get('utm_medium'),
            utm_campaign=current_utm.get('utm_campaign'),
            utm_term=current_utm.get('utm_term'),
            utm_content=current_utm.get('utm_content'),
        )

        # Check for identity resolution data
        if data['event_type'] == 'custom' and 'event_data' in data:
            event_data = data.get('event_data', {})
            if 'event_name' in event_data and event_data['event_name'] == 'identify':
                identity_data = event_data.get('identity_data', {})
                if 'email' in identity_data:
                    # Trigger identity resolution (async if Celery is available)
                    try:
                        process_identity_resolution.delay(
                            str(visitor.id),
                            identity_data
                        )
                    except Exception:
                        # Fallback to synchronous processing if Celery is not available
                        from .tasks import process_identity_resolution_sync
                        process_identity_resolution_sync(str(visitor.id), identity_data)
                        # Refresh visitor object to get updated is_identified status
                        visitor.refresh_from_db()

        # Build response with all available visitor data for frontend matching
        response_data = {
            'status': 'ok',
            'event_id': str(event.id),
            'visitor_id': visitor.visitor_id,
            'is_identified': visitor.is_identified,
            'visitor': {
                'ip_address': visitor.ip_address,
                'user_agent': visitor.user_agent,
                'browser_name': visitor.browser_name,
                'os_name': visitor.os_name,
                'device_type': visitor.device_type,
                'screen_resolution': visitor.screen_resolution,
                'timezone': visitor.timezone,
                'language': visitor.language,
                'referrer': visitor.referrer,
                'utm_source': visitor.utm_source,
                'utm_medium': visitor.utm_medium,
                'utm_campaign': visitor.utm_campaign,
                'utm_term': visitor.utm_term,
                'utm_content': visitor.utm_content,
                'first_seen': visitor.first_seen.isoformat() if visitor.first_seen else None,
                'last_seen': visitor.last_seen.isoformat() if visitor.last_seen else None,
                'matched_via': visitor.matched_via,
            }
        }

        # Note: Contact and enrichment data are intentionally not included
        # to prevent exposing PII of other users to the frontend

        return Response(response_data, status=status.HTTP_201_CREATED)

    except Site.DoesNotExist:
        return Response(
            {'error': 'Invalid site key'},
            status=status.HTTP_400_BAD_REQUEST
        )
    except Exception as e:
        import traceback
        error_details = {
            'error': str(e),
            'traceback': traceback.format_exc()
        }
        print(f"Tracking error: {error_details}")  # Log to console
        return Response(
            {'error': str(e), 'details': 'Check server logs for more information'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


class SiteViewSet(viewsets.ModelViewSet):
    queryset = Site.objects.all()
    serializer_class = SiteSerializer
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [HasAPIKeyOrIsStaff]

    def get_queryset(self):
        # If authenticated via API key, only show their site
        if hasattr(self.request, 'auth') and self.request.auth:
            return Site.objects.filter(id=self.request.user.id)
        # Staff users see all
        return Site.objects.all()


class VisitorViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Visitor.objects.all()
    serializer_class = VisitorSerializer
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [HasAPIKeyOrIsStaff]

    def get_queryset(self):
        queryset = Visitor.objects.all()

        # Filter by authenticated site
        if hasattr(self.request, 'auth') and self.request.auth:
            queryset = queryset.filter(site=self.request.user)

        # Additional filtering
        site_id = self.request.query_params.get('site', None)
        if site_id and self.request.user.is_staff:
            queryset = queryset.filter(site_id=site_id)

        return queryset


class ContactViewSet(viewsets.ModelViewSet):
    queryset = Contact.objects.all()
    serializer_class = ContactSerializer
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [HasAPIKeyOrIsStaff]

    def get_queryset(self):
        queryset = Contact.objects.all()

        # Filter by authenticated site
        if hasattr(self.request, 'auth') and self.request.auth:
            queryset = queryset.filter(site=self.request.user)

        # Additional filtering
        site_id = self.request.query_params.get('site', None)
        if site_id and self.request.user.is_staff:
            queryset = queryset.filter(site_id=site_id)

        return queryset


class EventViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Event.objects.all()
    serializer_class = EventSerializer
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [HasAPIKeyOrIsStaff]

    def get_queryset(self):
        queryset = Event.objects.all()

        # Filter by authenticated site
        if hasattr(self.request, 'auth') and self.request.auth:
            queryset = queryset.filter(site=self.request.user)

        # Additional filtering
        site_id = self.request.query_params.get('site', None)
        visitor_id = self.request.query_params.get('visitor', None)
        event_type = self.request.query_params.get('type', None)

        if site_id and self.request.user.is_staff:
            queryset = queryset.filter(site_id=site_id)
        if visitor_id:
            queryset = queryset.filter(visitor_id=visitor_id)
        if event_type:
            queryset = queryset.filter(event_type=event_type)

        return queryset.order_by('-timestamp')


class ConversionGoalViewSet(viewsets.ModelViewSet):
    queryset = ConversionGoal.objects.all()
    serializer_class = ConversionGoalSerializer
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [HasAPIKeyOrIsStaff]

    def get_queryset(self):
        queryset = ConversionGoal.objects.all()

        # Filter by authenticated site
        if hasattr(self.request, 'auth') and self.request.auth:
            queryset = queryset.filter(site=self.request.user)

        # Additional filtering
        site_id = self.request.query_params.get('site', None)
        if site_id and self.request.user.is_staff:
            queryset = queryset.filter(site_id=site_id)

        return queryset
