"""Static informational pages."""

from django.shortcuts import render


def faq_view(request):
    """FAQ page."""
    return render(request, 'webapp/faq.html', {
        'page_title': 'Frequently Asked Questions - Visa Bulletin Dashboard',
        'page_description': 'Common questions about priority dates, PERM processing, Final Action vs Filing Dates, and how the Visa Bulletin tracker works.',
    })


def about_view(request):
    """About page."""
    return render(request, 'webapp/about.html', {
        'page_title': 'About - Visa Bulletin Dashboard',
        'page_description': 'Learn about the Visa Bulletin dashboard, data sources, projection methodology, and the team behind this community tool.',
    })


def contact_view(request):
    """Contact page."""
    return render(request, 'webapp/contact.html', {
        'page_title': 'Contact - Visa Bulletin Dashboard',
        'page_description': 'Get in touch with questions, feedback, or bug reports about the Visa Bulletin tracker.',
    })
