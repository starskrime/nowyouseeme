from django.db import models
import uuid
import secrets
from django.utils import timezone


class Site(models.Model):
    """Represents a website/domain being tracked"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    domain = models.CharField(max_length=255, unique=True)
    site_key = models.CharField(max_length=64, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.domain})"

    def save(self, *args, **kwargs):
        if not self.site_key:
            self.site_key = str(uuid.uuid4())[:32]
        super().save(*args, **kwargs)


class Visitor(models.Model):
    """Represents an anonymous visitor with a unique tracking ID"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name='visitors')
    visitor_id = models.CharField(max_length=255, db_index=True)  # Cookie/fingerprint ID
    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)

    # Tracking data
    user_agent = models.TextField(blank=True, null=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True, db_index=True)
    referrer = models.TextField(blank=True, null=True)

    # Browser fingerprint data
    browser_name = models.CharField(max_length=100, blank=True, null=True)
    browser_version = models.CharField(max_length=50, blank=True, null=True)
    os_name = models.CharField(max_length=100, blank=True, null=True)
    device_type = models.CharField(max_length=50, blank=True, null=True)  # desktop, mobile, tablet
    screen_resolution = models.CharField(max_length=50, blank=True, null=True)
    timezone = models.CharField(max_length=100, blank=True, null=True)
    language = models.CharField(max_length=10, blank=True, null=True)

    # Identity resolution
    is_identified = models.BooleanField(default=False)
    matched_via = models.CharField(max_length=50, blank=True, null=True)  # ip, email, phone, etc.

    # UTM parameters (first-touch attribution)
    utm_source = models.CharField(max_length=255, blank=True, null=True)
    utm_medium = models.CharField(max_length=255, blank=True, null=True)
    utm_campaign = models.CharField(max_length=255, blank=True, null=True)
    utm_term = models.CharField(max_length=255, blank=True, null=True)
    utm_content = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        ordering = ['-last_seen']
        unique_together = [['site', 'visitor_id']]
        indexes = [
            models.Index(fields=['site', 'visitor_id']),
            models.Index(fields=['is_identified']),
        ]

    def __str__(self):
        return f"Visitor {self.visitor_id[:8]}... on {self.site.name}"


class Contact(models.Model):
    """Represents an identified contact (email + visitor data)"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name='contacts')
    visitor = models.OneToOneField(Visitor, on_delete=models.CASCADE, related_name='contact', null=True, blank=True)

    # Link to enrichment data if matched
    enrichment_data = models.ForeignKey('EnrichmentData', on_delete=models.SET_NULL, null=True, blank=True, related_name='contacts')

    # Identity information
    email = models.EmailField(db_index=True)
    name = models.CharField(max_length=255, blank=True, null=True)
    phone = models.CharField(max_length=50, blank=True, null=True)

    # Social profiles (can be populated from enrichment data)
    linkedin_url = models.URLField(blank=True, null=True)
    facebook_url = models.URLField(blank=True, null=True)

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Additional data (flexible JSON field for extra attributes)
    extra_data = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = [['site', 'email']]
        indexes = [
            models.Index(fields=['site', 'email']),
        ]

    def __str__(self):
        return f"{self.email} ({self.site.name})"

    def delete(self, *args, **kwargs):
        """
        Override delete to also delete associated EnrichmentData and reset Visitor.
        This prevents auto-recreation of the contact when they visit again.

        If the EnrichmentData is linked to other Contacts, only this Contact is deleted.
        If this is the last Contact using the EnrichmentData, the EnrichmentData is also deleted.
        """
        enrichment = self.enrichment_data
        visitor = self.visitor

        # Delete the contact first
        result = super().delete(*args, **kwargs)

        # Reset visitor identification status since their contact was deleted
        if visitor:
            visitor.is_identified = False
            visitor.matched_via = None
            visitor.save()

        # If there was enrichment data, check if it should also be deleted
        if enrichment:
            # Check if any other contacts are still using this enrichment data
            remaining_contacts = Contact.objects.filter(enrichment_data=enrichment).exists()

            if not remaining_contacts:
                # This was the last contact using this enrichment data, delete it
                enrichment.delete()

        return result


class EnrichmentData(models.Model):
    """
    Stores enrichment data from CSV uploads for identity matching
    This is the "database" of known people that we match against
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name='enrichment_data')

    # Identity fields
    first_name = models.CharField(max_length=255, blank=True, null=True)
    last_name = models.CharField(max_length=255, blank=True, null=True)
    email = models.EmailField(db_index=True)
    phone = models.CharField(max_length=50, blank=True, null=True)

    # Social profiles
    linkedin_url = models.URLField(blank=True, null=True)
    facebook_url = models.URLField(blank=True, null=True)
    twitter_url = models.URLField(blank=True, null=True)

    # Technical identifiers for matching
    ip_addresses = models.JSONField(default=list, blank=True)  # List of known IPs
    phone_numbers = models.JSONField(default=list, blank=True)  # List of known phone numbers
    user_agents = models.JSONField(default=list, blank=True)  # List of known user agents

    # Browser fingerprints for matching (stored as JSON array of fingerprint objects)
    browser_fingerprints = models.JSONField(default=list, blank=True)  # List of known browser fingerprints

    # Additional enrichment data
    company = models.CharField(max_length=255, blank=True, null=True)
    job_title = models.CharField(max_length=255, blank=True, null=True)
    location = models.CharField(max_length=255, blank=True, null=True)

    # Metadata
    source = models.CharField(max_length=100, default='csv_upload')  # csv_upload, api, manual, etc.
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Extra flexible data
    extra_data = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = [['site', 'email']]
        indexes = [
            models.Index(fields=['site', 'email']),
        ]
        verbose_name_plural = 'Enrichment data'

    def __str__(self):
        name = f"{self.first_name} {self.last_name}".strip() or self.email
        return f"{name} ({self.site.name})"


class Event(models.Model):
    """Represents a tracking event (page view, cart view, etc.)"""

    EVENT_TYPES = [
        ('page_view', 'Page View'),
        ('cart_view', 'Cart View'),
        ('cart_add', 'Add to Cart'),
        ('checkout_start', 'Checkout Started'),
        ('purchase', 'Purchase'),
        ('form_submit', 'Form Submit'),
        ('custom', 'Custom Event'),
        # Abandonment events
        ('browse_abandonment', 'Browse Abandonment'),
        ('product_view', 'Product View'),
        ('product_abandonment', 'Product Abandonment'),
        ('cart_abandonment', 'Cart Abandonment'),
        ('checkout_abandonment', 'Checkout Abandonment'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name='events')
    visitor = models.ForeignKey(Visitor, on_delete=models.CASCADE, related_name='events')

    # Event details
    event_type = models.CharField(max_length=50, choices=EVENT_TYPES, db_index=True)
    event_name = models.CharField(max_length=255, blank=True, null=True)

    # Page/URL info
    page_url = models.TextField()
    page_title = models.CharField(max_length=500, blank=True, null=True)

    # Event data (flexible JSON for cart items, form data, etc.)
    event_data = models.JSONField(default=dict, blank=True)

    # UTM parameters (last-touch attribution per event)
    utm_source = models.CharField(max_length=255, blank=True, null=True)
    utm_medium = models.CharField(max_length=255, blank=True, null=True)
    utm_campaign = models.CharField(max_length=255, blank=True, null=True)
    utm_term = models.CharField(max_length=255, blank=True, null=True)
    utm_content = models.CharField(max_length=255, blank=True, null=True)
    referrer = models.TextField(blank=True, null=True)

    # Metadata
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    session_id = models.CharField(max_length=255, blank=True, null=True, db_index=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['site', 'event_type', '-timestamp']),
            models.Index(fields=['visitor', '-timestamp']),
            models.Index(fields=['session_id', '-timestamp']),
        ]

    def __str__(self):
        return f"{self.event_type} on {self.site.name} at {self.timestamp}"


class ConversionGoal(models.Model):
    """Defines conversion goals for tracking"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name='conversion_goals')
    name = models.CharField(max_length=255)
    event_type = models.CharField(max_length=50)

    # Conditions for conversion (e.g., URL patterns, event data filters)
    conditions = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.site.name})"


class APIKey(models.Model):
    """API key for authenticating REST API requests"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name='api_keys')
    name = models.CharField(max_length=255, help_text="Descriptive name for this API key")
    key = models.CharField(max_length=64, unique=True, db_index=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} - {self.site.name}"

    def save(self, *args, **kwargs):
        if not self.key:
            self.key = 'sk_' + secrets.token_urlsafe(32)
        super().save(*args, **kwargs)
