from django.contrib import admin
from django.shortcuts import render, redirect
from django.urls import path
from django.contrib import messages
import csv
import io
from .models import Site, Visitor, Contact, Event, ConversionGoal, EnrichmentData, APIKey


@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    list_display = ('name', 'domain', 'site_key', 'is_active', 'created_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('name', 'domain', 'site_key')
    readonly_fields = ('id', 'site_key', 'created_at')


@admin.register(Visitor)
class VisitorAdmin(admin.ModelAdmin):
    list_display = ('visitor_id', 'site', 'is_identified', 'first_seen', 'last_seen')
    list_filter = ('is_identified', 'site', 'first_seen')
    search_fields = ('visitor_id', 'ip_address')
    readonly_fields = ('id', 'first_seen', 'last_seen')
    raw_id_fields = ('site',)


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ('email', 'name', 'site', 'created_at')
    list_filter = ('site', 'created_at')
    search_fields = ('email', 'name', 'phone')
    readonly_fields = ('id', 'created_at', 'updated_at')
    raw_id_fields = ('site', 'visitor')


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ('event_type', 'event_name', 'site', 'visitor', 'timestamp')
    list_filter = ('event_type', 'site', 'timestamp')
    search_fields = ('event_name', 'page_url', 'page_title')
    readonly_fields = ('id', 'timestamp')
    raw_id_fields = ('site', 'visitor')
    date_hierarchy = 'timestamp'


@admin.register(ConversionGoal)
class ConversionGoalAdmin(admin.ModelAdmin):
    list_display = ('name', 'site', 'event_type', 'is_active', 'created_at')
    list_filter = ('is_active', 'site', 'event_type')
    search_fields = ('name',)
    readonly_fields = ('id', 'created_at')
    raw_id_fields = ('site',)


@admin.register(EnrichmentData)
class EnrichmentDataAdmin(admin.ModelAdmin):
    list_display = ('email', 'first_name', 'last_name', 'company', 'site', 'source', 'created_at')
    list_filter = ('site', 'source', 'created_at')
    search_fields = ('email', 'first_name', 'last_name', 'company', 'phone')
    readonly_fields = ('id', 'created_at', 'updated_at')
    raw_id_fields = ('site',)

    change_list_template = "admin/enrichment_data_changelist.html"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('upload-csv/', self.upload_csv, name='enrichment_upload_csv'),
        ]
        return custom_urls + urls

    def upload_csv(self, request):
        if request.method == "POST":
            csv_file = request.FILES.get("csv_file")
            site_id = request.POST.get("site")

            if not csv_file:
                messages.error(request, "Please select a CSV file to upload.")
                return redirect("..")

            if not site_id:
                messages.error(request, "Please select a site.")
                return redirect("..")

            try:
                site = Site.objects.get(id=site_id)
            except Site.DoesNotExist:
                messages.error(request, "Invalid site selected.")
                return redirect("..")

            # Read CSV
            try:
                decoded_file = csv_file.read().decode('utf-8')
                io_string = io.StringIO(decoded_file)
                reader = csv.DictReader(io_string)

                created_count = 0
                updated_count = 0
                errors = []

                for row_num, row in enumerate(reader, start=2):
                    try:
                        email = row.get('email', '').strip()
                        if not email:
                            errors.append(f"Row {row_num}: Missing email")
                            continue

                        # Parse IP addresses (can be comma-separated)
                        ip_addresses = []
                        ip_field = row.get('ip_address', '') or row.get('ip', '')
                        if ip_field:
                            ip_addresses = [ip.strip() for ip in ip_field.split(',') if ip.strip()]

                        # Get or create enrichment data
                        enrichment, created = EnrichmentData.objects.update_or_create(
                            site=site,
                            email=email,
                            defaults={
                                'first_name': row.get('first_name', '') or row.get('firstname', ''),
                                'last_name': row.get('last_name', '') or row.get('lastname', ''),
                                'phone': row.get('phone', '') or row.get('phone_number', ''),
                                'linkedin_url': row.get('linkedin_url', '') or row.get('linkedin', ''),
                                'facebook_url': row.get('facebook_url', '') or row.get('facebook', ''),
                                'twitter_url': row.get('twitter_url', '') or row.get('twitter', ''),
                                'company': row.get('company', ''),
                                'job_title': row.get('job_title', '') or row.get('title', ''),
                                'location': row.get('location', ''),
                                'ip_addresses': ip_addresses,
                                'source': 'csv_upload',
                            }
                        )

                        if created:
                            created_count += 1
                        else:
                            updated_count += 1

                    except Exception as e:
                        errors.append(f"Row {row_num}: {str(e)}")

                # Show results
                success_msg = f"Successfully imported {created_count} new records and updated {updated_count} existing records."
                messages.success(request, success_msg)

                if errors:
                    error_msg = f"Encountered {len(errors)} errors. First few: " + "; ".join(errors[:5])
                    messages.warning(request, error_msg)

            except Exception as e:
                messages.error(request, f"Error processing CSV: {str(e)}")

            return redirect("..")

        # GET request - show form
        sites = Site.objects.filter(is_active=True)
        context = {
            'sites': sites,
            'title': 'Upload Enrichment Data CSV',
        }
        return render(request, "admin/enrichment_upload_form.html", context)


@admin.register(APIKey)
class APIKeyAdmin(admin.ModelAdmin):
    list_display = ('name', 'site', 'key_preview', 'is_active', 'created_at', 'last_used')
    list_filter = ('is_active', 'site', 'created_at')
    search_fields = ('name', 'key')
    readonly_fields = ('id', 'key', 'created_at', 'last_used')
    raw_id_fields = ('site',)

    def key_preview(self, obj):
        """Show first and last 4 characters of API key"""
        if obj.key and len(obj.key) > 8:
            return f"{obj.key[:8]}...{obj.key[-4:]}"
        return obj.key
    key_preview.short_description = 'API Key'
