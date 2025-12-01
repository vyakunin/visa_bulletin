# Visa Bulletin Web Dashboard

## Overview

Interactive web dashboard for visualizing U.S. visa bulletin priority date trends and estimating processing times.

## Quick Start

```bash
# Start the web server
bazel run //:runserver

# Open browser to http://localhost:8000/
```

## Features

### 📊 Interactive Charting
- **Plotly charts** showing historical priority date progression
- Hover tooltips with exact dates
- Responsive design that works on desktop and mobile

### 🔮 Processing Projections
- Simple linear projection based on recent progress rate (last 12 months)
- Estimated wait time calculation
- Disclaimer noting projections are estimates

### 🎯 Deep Linking
- All filter selections encoded in URL query parameters
- Share specific views with colleagues/family
- Bookmark favorite combinations

### 🔍 Filter Options
- **Visa Category**: Family-Sponsored, Employment-Based
- **Country**: All, China, India, Mexico, Philippines, El Salvador/Guatemala/Honduras
- **Visa Class**: F1, F2A, F2B, F3, F4, EB1, EB2, EB3, EB4, EB5
- **Action Type**: Final Action (green card approval), Filing (I-485 submission)
- **Submission Date**: Your priority date (defaults to today)

## Architecture

### Tech Stack
- **Backend**: Django 5.0
- **Frontend**: Bootstrap 5 + Plotly.js
- **Database**: SQLite (13,000+ cutoff date records)
- **Build**: Bazel (hermetic builds)

### Project Structure

```
webapp/
├── views.py                    # Main dashboard view + projection logic
├── urls.py                     # URL routing
├── apps.py                     # Django app config
└── templates/webapp/
    ├── base.html              # Base template with Bootstrap 5
    └── dashboard.html         # Main dashboard page
```

### Key Components

**1. Dashboard View (`views.py`)**
- Handles query parameter parsing
- Queries `VisaCutoffDate` model with filters
- Calculates projection based on historical trends
- Renders Plotly chart and passes to template

**2. Projection Algorithm (`calculate_projection`)**
- Uses last 12 months of data
- Computes average monthly progress (days advanced per month)
- Extrapolates to estimate when priority date will be reached
- Handles edge cases (already current, no movement, regressive trends)

**3. Templates**
- `base.html`: Bootstrap 5 layout with responsive nav
- `dashboard.html`: Filter form + Plotly chart + projection alert

## URL Structure

Deep-linkable query parameters:

```
http://localhost:8000/?category=family_sponsored&country=china&visa_class=F1&action_type=final_action&submission_date=2020-01-15
```

**Parameters:**
- `category`: `family_sponsored` | `employment_based`
- `country`: `all` | `china` | `india` | `mexico` | `philippines` | `el_salvador_guatemala_honduras`
- `visa_class`: `F1` | `F2A` | `F2B` | `F3` | `F4` | `EB1` | `EB2` | `EB3` | `EB4` | `EB5`
- `action_type`: `final_action` | `dates_for_filing`
- `submission_date`: `YYYY-MM-DD` (defaults to today)

## Data Pipeline

```
1. fetch_main_page()
   ↓
2. parse_publication_links()
   ↓
3. maybe_fetch_publication() [cached]
   ↓
4. extract_tables()
   ↓
5. BulletinExtractor.extract_from_table()
   ↓
6. save_bulletin_to_db()
   ↓
7. Dashboard queries VisaCutoffDate model
   ↓
8. Plotly chart rendered in browser
```

## Projection Algorithm

### Formula

```
avg_days_per_month = (last_cutoff - first_cutoff) / months_elapsed
months_to_wait = (submission_date - current_cutoff) / avg_days_per_month
estimated_date = current_bulletin_date + months_to_wait
```

### Example

```
Data: Last 12 months, F1 China Final Action
- Oct 2024: 2015-10-22
- Oct 2025: 2016-11-08
- Progress: 382 days in 12 months = 31.8 days/month

Submission date: 2020-01-01
Days to advance: 1,150 days
Estimated wait: 1,150 / 31.8 = 36 months
Estimated processing: Oct 2025 + 36 months = Oct 2028
```

### Limitations

- **Assumes linear progression** (reality is often non-linear)
- **Ignores policy changes** (DHS backlogs, USCIS processing changes)
- **No confidence intervals** (simple point estimate)
- **Short lookback window** (12 months, misses longer-term trends)

### Use Cases

✅ **Good for:**
- Rough ballpark estimates
- Comparing relative wait times across categories
- Spotting categories with faster movement

❌ **Not good for:**
- Making financial commitments (home purchase, etc.)
- Precise timeline planning
- Legal advice

## Development

### Adding New Features

1. **New filter**: Update `dashboard_view()` to parse param, add to template form
2. **Chart enhancement**: Modify `build_chart_with_projection()` in `views.py`
3. **New projection algorithm**: Update `calculate_projection()`

### Testing

```bash
# Run all tests (includes webapp dependencies)
bazel test //tests:test_parser //tests:test_extractor //tests:test_integration

# Test specific functionality
bazel test //tests:test_integration --test_output=all
```

### Dependencies

**Python packages** (in `requirements.txt`):
- `Django>=5.0` - Web framework
- `plotly>=5.18.0` - Interactive charts
- `tenacity>=8.2.0` - Retry logic (plotly dependency)
- `narwhals>=2.0.0` - Data manipulation (plotly dependency)

**Bazel targets**:
- `//:runserver` - Django development server
- `//webapp:views` - Dashboard view logic
- `//webapp:templates` - HTML templates

## Deployment Notes

**Current setup is for development only:**
- `DEBUG = True` in settings
- `SECRET_KEY` is hardcoded
- `ALLOWED_HOSTS = ['*']`
- SQLite database (not scalable)

**For production:**
1. Use environment variables for secrets
2. Switch to PostgreSQL/MySQL
3. Configure static file serving (WhiteNoise or CDN)
4. Use WSGI server (gunicorn, uWSGI)
5. Set `DEBUG = False`
6. Configure proper `ALLOWED_HOSTS`
7. Add CSRF/security middleware
8. Set up HTTPS

## Troubleshooting

### Server won't start
```bash
# Check if port 8000 is already in use
lsof -i :8000
kill -9 <PID>

# Rebuild and try again
bazel clean
bazel run //:runserver
```

### No data showing
```bash
# Import bulletins first
bazel run //:refresh_data -- --save-to-db

# Verify data exists
sqlite3 visa_bulletin.db "SELECT COUNT(*) FROM visa_cutoff_date;"
```

### Chart not rendering
- Check browser console for JavaScript errors
- Verify Plotly CDN is accessible
- Clear browser cache and reload

### Projection says "no movement"
- Category may have retrogressed recently
- Try different visa class or country
- Check official visa bulletin for context

## Future Enhancements

Possible improvements:
- **Historical comparison**: Overlay multiple countries on one chart
- **Alerts**: Email notifications when priority date advances
- **Advanced projections**: Monte Carlo simulation, confidence intervals
- **Category comparison**: Side-by-side charts for different visa classes
- **Export**: Download chart as PNG or data as CSV
- **API**: REST API for programmatic access
- **Mobile app**: Native iOS/Android app

## License

See main README.md for project license.

