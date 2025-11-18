#!/bin/bash

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Retention Analytics - Setup Script  ${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo -e "${YELLOW}Python 3 is not installed. Please install Python 3.8 or higher.${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Python 3 found${NC}"

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo -e "${BLUE}Creating virtual environment...${NC}"
    python3 -m venv venv
    echo -e "${GREEN}✓ Virtual environment created${NC}"
else
    echo -e "${GREEN}✓ Virtual environment already exists${NC}"
fi

# Activate virtual environment
echo -e "${BLUE}Activating virtual environment...${NC}"
source venv/bin/activate

# Install/update dependencies
echo -e "${BLUE}Installing dependencies...${NC}"
pip install --upgrade pip > /dev/null 2>&1
pip install -r requirements.txt
echo -e "${GREEN}✓ Dependencies installed${NC}"

# Run migrations
echo -e "${BLUE}Running database migrations...${NC}"
python manage.py migrate
echo -e "${GREEN}✓ Database migrated${NC}"

# Collect static files
echo -e "${BLUE}Collecting static files...${NC}"
python manage.py collectstatic --noinput > /dev/null 2>&1
echo -e "${GREEN}✓ Static files collected${NC}"

# Check if superuser exists
echo ""
echo -e "${YELLOW}Checking for admin user...${NC}"
python manage.py shell -c "from django.contrib.auth import get_user_model; User = get_user_model(); exit(0 if User.objects.filter(is_superuser=True).exists() else 1)"

if [ $? -ne 0 ]; then
    echo -e "${YELLOW}No admin user found. Let's create one:${NC}"
    echo ""
    python manage.py createsuperuser
else
    echo -e "${GREEN}✓ Admin user already exists${NC}"
fi

# Create demo site if it doesn't exist and upload sample enrichment data
echo ""
echo -e "${BLUE}Setting up demo data...${NC}"
python manage.py shell << 'PYEOF'
import csv
from tracking.models import Site, EnrichmentData

# Create or get demo site
site, created = Site.objects.get_or_create(
    name='DemoSite',
    defaults={
        'domain': 'localhost',
        'is_active': True
    }
)

if created:
    print(f"✓ Created demo site: {site.name} (key: {site.site_key})")
else:
    print(f"✓ Demo site already exists: {site.name}")

# Upload/update sample enrichment data
csv_file = 'sample_enrichment_data.csv'
try:
    with open(csv_file, 'r') as f:
        reader = csv.DictReader(f)
        created_count = 0
        updated_count = 0
        csv_emails = []
        csv_ip_map = {}  # Map IP to email from CSV

        for row in reader:
            email = row.get('email', '').strip()
            if not email:
                continue

            csv_emails.append(email)

            # Parse IP addresses
            ip_addresses = []
            ip_field = row.get('ip_address', '') or row.get('ip', '')
            if ip_field:
                ip_addresses = [ip.strip() for ip in ip_field.split(',') if ip.strip()]
                # Map each IP to this email
                for ip in ip_addresses:
                    csv_ip_map[ip] = email

            # Create or update enrichment data
            enrichment, created = EnrichmentData.objects.update_or_create(
                site=site,
                email=email,
                defaults={
                    'first_name': row.get('first_name', ''),
                    'last_name': row.get('last_name', ''),
                    'phone': row.get('phone', ''),
                    'linkedin_url': row.get('linkedin_url', ''),
                    'facebook_url': row.get('facebook_url', ''),
                    'twitter_url': row.get('twitter_url', ''),
                    'company': row.get('company', ''),
                    'job_title': row.get('job_title', ''),
                    'location': row.get('location', ''),
                    'ip_addresses': ip_addresses,
                    'source': 'csv_upload',
                }
            )

            if created:
                created_count += 1
            else:
                updated_count += 1

    # Delete enrichment records not in CSV (cleanup)
    from tracking.models import Contact
    deleted_count = 0
    for old_enrichment in EnrichmentData.objects.filter(site=site, source='csv_upload').exclude(email__in=csv_emails):
        # Check if this enrichment has an IP that's now mapped to a different email
        for ip in old_enrichment.ip_addresses:
            if ip in csv_ip_map:
                new_email = csv_ip_map[ip]
                # Find contacts linked to this old enrichment
                for contact in Contact.objects.filter(enrichment_data=old_enrichment):
                    # Link to new enrichment
                    new_enrichment = EnrichmentData.objects.filter(site=site, email=new_email).first()
                    if new_enrichment:
                        contact.email = new_enrichment.email
                        contact.enrichment_data = new_enrichment
                        contact.name = f"{new_enrichment.first_name} {new_enrichment.last_name}".strip()
                        contact.phone = new_enrichment.phone
                        contact.linkedin_url = new_enrichment.linkedin_url
                        contact.facebook_url = new_enrichment.facebook_url
                        contact.save()
                        print(f"  → Migrated contact to new email: {new_email}")

        old_enrichment.delete()
        deleted_count += 1

    if created_count > 0 or updated_count > 0:
        print(f"✓ Uploaded {created_count} new and updated {updated_count} existing enrichment records")
    if deleted_count > 0:
        print(f"✓ Cleaned up {deleted_count} old enrichment records")
except FileNotFoundError:
    print("⚠ sample_enrichment_data.csv not found, skipping enrichment upload")

# Update existing contacts with new enrichment data
updated_contacts = 0
for contact in Contact.objects.filter(site=site, enrichment_data__isnull=False):
    enrichment = contact.enrichment_data
    contact.name = f"{enrichment.first_name} {enrichment.last_name}".strip()
    contact.phone = enrichment.phone
    contact.linkedin_url = enrichment.linkedin_url
    contact.facebook_url = enrichment.facebook_url
    contact.save()
    updated_contacts += 1

if updated_contacts > 0:
    print(f"✓ Updated {updated_contacts} contacts with new enrichment data")

PYEOF
echo -e "${GREEN}✓ Demo data setup complete${NC}"

echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}  Setup Complete! Starting Server...  ${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Kill any existing Django servers
echo -e "${BLUE}Checking for existing Django servers...${NC}"
EXISTING_PIDS=$(pgrep -f "python manage.py runserver" || true)
if [ ! -z "$EXISTING_PIDS" ]; then
    echo -e "${YELLOW}Found running Django server(s), stopping them...${NC}"
    pkill -f "python manage.py runserver" || true
    sleep 2
    echo -e "${GREEN}✓ Existing server(s) stopped${NC}"
else
    echo -e "${GREEN}✓ No existing servers found${NC}"
fi

echo ""
echo -e "${YELLOW}Access the application at:${NC}"
echo -e "  Dashboard:   ${GREEN}http://localhost:8000/dashboard/${NC}"
echo -e "  Admin Panel: ${GREEN}http://localhost:8000/admin/${NC}"
echo -e "  Demo Page:   ${GREEN}http://localhost:8000/demo/${NC}"
echo -e "  API:         ${GREEN}http://localhost:8000/api/${NC}"
echo ""
echo -e "${YELLOW}Quick Test: Visit /demo/ to see IP-based visitor identification in action!${NC}"
echo -e "${YELLOW}(Sample enrichment data includes 127.0.0.1 for automatic matching)${NC}"
echo ""
echo -e "${YELLOW}Press Ctrl+C to stop the server${NC}"
echo ""

# Start the development server
python manage.py runserver
