# Generated manually on 2026-01-05
# Data migration to populate slug field for existing EmployerCluster records

from django.db import migrations
from django.utils.text import slugify


def populate_slugs(apps, schema_editor):
    """Generate and populate slugs for all existing EmployerCluster records"""
    EmployerCluster = apps.get_model('models', 'EmployerCluster')
    
    # Track used slugs to ensure uniqueness
    used_slugs = set()
    
    for cluster in EmployerCluster.objects.all():
        if not cluster.slug and cluster.canonical_name:
            # Generate base slug
            base_slug = slugify(cluster.canonical_name)
            
            # Ensure uniqueness
            slug = base_slug
            counter = 1
            while slug in used_slugs or EmployerCluster.objects.filter(slug=slug).exclude(pk=cluster.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            
            # Set slug and save
            cluster.slug = slug
            cluster.save(update_fields=['slug'])
            used_slugs.add(slug)


def reverse_populate_slugs(apps, schema_editor):
    """Clear all slugs (for migration reversal)"""
    EmployerCluster = apps.get_model('models', 'EmployerCluster')
    EmployerCluster.objects.all().update(slug=None)


class Migration(migrations.Migration):

    dependencies = [
        ('models', '0021_employercluster_slug_and_more'),
    ]

    operations = [
        migrations.RunPython(populate_slugs, reverse_populate_slugs),
    ]

