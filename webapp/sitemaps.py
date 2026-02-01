"""Sitemap configuration for webapp"""

from django.contrib.sitemaps import Sitemap
from models.salary import EmployerCluster


class EmployerSitemap(Sitemap):
    """Sitemap for employer profile pages"""
    
    changefreq = "monthly"
    priority = 0.7
    protocol = "https"
    
    def items(self):
        """Return all employer clusters with at least 5 filings"""
        return EmployerCluster.objects.filter(
            slug__isnull=False,
            total_lca_count__gte=5
        ).order_by('-total_lca_count')
    
    def location(self, obj):
        """Return URL path for employer profile"""
        return f'/employer/{obj.slug}/'
    
    def lastmod(self, obj):
        """Return last modification date"""
        return obj.updated_at

