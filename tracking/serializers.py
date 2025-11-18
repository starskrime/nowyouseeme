from rest_framework import serializers
from .models import Site, Visitor, Contact, Event, ConversionGoal


class SiteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Site
        fields = ['id', 'name', 'domain', 'site_key', 'created_at', 'is_active']
        read_only_fields = ['id', 'site_key', 'created_at']


class VisitorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Visitor
        fields = [
            'id', 'visitor_id', 'site', 'first_seen', 'last_seen',
            'user_agent', 'ip_address', 'referrer', 'is_identified'
        ]
        read_only_fields = ['id', 'first_seen', 'last_seen']


class ContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contact
        fields = [
            'id', 'email', 'name', 'phone', 'site', 'visitor',
            'extra_data', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class EventSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = [
            'id', 'site', 'visitor', 'event_type', 'event_name',
            'page_url', 'page_title', 'event_data', 'timestamp', 'session_id'
        ]
        read_only_fields = ['id', 'timestamp']


class TrackEventSerializer(serializers.Serializer):
    """
    Serializer for incoming tracking events from the pixel

    IMPORTANT: This serializer explicitly excludes identification-related fields
    (is_identified, matched_via, etc.) to prevent client-side manipulation.
    Visitor identification is ALWAYS determined server-side based on matching logic.
    """
    site_key = serializers.CharField(max_length=64)
    visitor_id = serializers.CharField(max_length=255)
    session_id = serializers.CharField(max_length=255, required=False, allow_blank=True)
    event_type = serializers.CharField(max_length=50)
    event_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    page_url = serializers.URLField()
    page_title = serializers.CharField(max_length=500, required=False, allow_blank=True)
    referrer = serializers.URLField(required=False, allow_blank=True)
    event_data = serializers.JSONField(required=False, default=dict)
    browser_fingerprint = serializers.JSONField(required=False, default=dict)
    utm_params = serializers.JSONField(required=False, default=dict)
    stored_utm_params = serializers.JSONField(required=False, default=dict)

    def validate_site_key(self, value):
        """Validate that the site key exists"""
        try:
            Site.objects.get(site_key=value, is_active=True)
        except Site.DoesNotExist:
            raise serializers.ValidationError("Invalid site key")
        return value


class ConversionGoalSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConversionGoal
        fields = ['id', 'site', 'name', 'event_type', 'conditions', 'created_at', 'is_active']
        read_only_fields = ['id', 'created_at']
