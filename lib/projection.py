"""
Projection logic for estimating visa processing timelines

Calculates simple linear projections based on historical priority date movement.
Falls back to historical linear regression when recent data shows no progress.
"""

from datetime import date, timedelta


def calculate_projection(dates: list[date], cutoff_dates: list[date | None], submission_date: date) -> dict[str, any] | None:
    """
    Calculate simple projection based on recent progress rate
    
    Args:
        dates: List of publication dates (bulletin release dates)
        cutoff_dates: List of cutoff dates (may contain None for unavailable)
        submission_date: Target submission date to reach
        
    Returns:
        dict with projection info:
            - status: 'current' | 'no_movement' | 'projected'
            - message: Human-readable status message
            - estimated_date: Projected date when submission_date will be reached (or None)
            - months_to_wait: Estimated months until processing (or None)
            - avg_progress_days_per_month: Average progress rate
        
        Returns None if insufficient data for projection
    
    Example:
        >>> dates = [date(2024, 1, 1), date(2024, 2, 1), date(2024, 3, 1)]
        >>> cutoffs = [date(2020, 1, 1), date(2020, 2, 1), date(2020, 3, 1)]
        >>> submission = date(2021, 1, 1)
        >>> result = calculate_projection(dates, cutoffs, submission)
        >>> result['status']
        'projected'
    """
    if len(dates) < 2:
        return None
    
    # Filter out None values and get recent data (last 12 months for stability)
    valid_points = [
        (pub_date, cutoff) for pub_date, cutoff in zip(dates, cutoff_dates) 
        if cutoff is not None
    ]
    
    if len(valid_points) < 2:
        return None
    
    # Use last 12 months for projection
    recent_points = valid_points[-12:]
    
    # Calculate monthly progress rate
    first_pub, first_cutoff = recent_points[0]
    last_pub, last_cutoff = recent_points[-1]
    
    months_elapsed = calculate_months_between(first_pub, last_pub)
    if months_elapsed == 0:
        months_elapsed = 1
    
    days_advanced = (last_cutoff - first_cutoff).days
    avg_days_per_month = days_advanced / months_elapsed
    
    # Check if already current or no movement
    if last_cutoff >= submission_date:
        return {
            'status': 'current',
            'message': 'Your application date has already been reached!',
            'estimated_date': None,
            'months_to_wait': 0,
        }
    
    if avg_days_per_month <= 0:
        # No recent progress - fall back to historical linear regression
        historical_projection = calculate_historical_linear_regression(
            valid_points, submission_date, last_pub
        )
        if historical_projection:
            return historical_projection
        
        # If historical regression also fails, return no movement
        return {
            'status': 'no_movement',
            'message': 'No forward progress detected in recent months.',
            'estimated_date': None,
            'months_to_wait': None,
        }
    
    # Calculate estimated wait time
    days_to_advance = (submission_date - last_cutoff).days
    months_to_wait = days_to_advance / avg_days_per_month
    
    # Project future date
    estimated_date = add_months_to_date(last_pub, int(months_to_wait))
    
    return {
        'status': 'projected',
        'message': f'Estimated processing in {int(months_to_wait)} months',
        'estimated_date': estimated_date,
        'months_to_wait': int(months_to_wait),
        'avg_progress_days_per_month': round(avg_days_per_month, 1),
    }


def calculate_months_between(start_date: date, end_date: date) -> int:
    """
    Calculate number of months between two dates
    
    Args:
        start_date: Earlier date
        end_date: Later date
        
    Returns:
        Number of months (integer)
        
    Example:
        >>> calculate_months_between(date(2024, 1, 15), date(2024, 3, 20))
        2
        >>> calculate_months_between(date(2023, 12, 1), date(2024, 2, 1))
        2
    """
    return (end_date.year - start_date.year) * 12 + (end_date.month - start_date.month)


def add_months_to_date(start_date: date, months: int) -> date:
    """
    Add specified number of months to a date
    
    Args:
        start_date: Starting date
        months: Number of months to add
        
    Returns:
        New date after adding months
        
    Example:
        >>> add_months_to_date(date(2024, 1, 15), 3)
        date(2024, 4, 15)
        >>> add_months_to_date(date(2024, 11, 30), 3)
        date(2025, 2, 28)
    """
    # Simple approximation: use 30 days per month
    return start_date + timedelta(days=months * 30)


def calculate_historical_linear_regression(
    valid_points: list[tuple[date, date]], 
    submission_date: date,
    last_pub_date: date
) -> dict[str, any] | None:
    """
    Calculate projection using linear regression on all historical data
    
    Used as fallback when recent data shows no progress. Fits a line through
    all historical points and extrapolates when the submission_date will be reached.
    
    Args:
        valid_points: List of (publication_date, cutoff_date) tuples
        submission_date: Target submission date to reach
        last_pub_date: Most recent bulletin publication date
        
    Returns:
        dict with projection info (same format as calculate_projection)
        Returns None if regression slope is not positive
        
    Example:
        >>> points = [(date(2020, 1, 1), date(2010, 1, 1)), ...]
        >>> submission = date(2015, 1, 1)
        >>> last_pub = date(2025, 1, 1)
        >>> result = calculate_historical_linear_regression(points, submission, last_pub)
    """
    if len(valid_points) < 6:  # Need reasonable historical data
        return None
    
    # Convert dates to days since epoch for linear regression
    epoch = date(2000, 1, 1)
    
    x_values = [(pub_date - epoch).days for pub_date, _ in valid_points]
    y_values = [(cutoff - epoch).days for _, cutoff in valid_points]
    
    # Calculate linear regression: y = mx + b
    n = len(x_values)
    sum_x = sum(x_values)
    sum_y = sum(y_values)
    sum_xy = sum(x * y for x, y in zip(x_values, y_values))
    sum_x_squared = sum(x * x for x in x_values)
    
    # Slope (m) and intercept (b)
    denominator = n * sum_x_squared - sum_x * sum_x
    if denominator == 0:
        return None
    
    slope = (n * sum_xy - sum_x * sum_y) / denominator
    intercept = (sum_y - slope * sum_x) / n
    
    # Check if slope is positive (forward progress)
    if slope <= 0:
        return None
    
    # Calculate when submission_date will be reached
    # We need: cutoff_date = submission_date
    # So: submission_date_days = slope * pub_date_days + intercept
    # Solving for pub_date_days: pub_date_days = (submission_date_days - intercept) / slope
    
    submission_days = (submission_date - epoch).days
    last_cutoff_days = slope * (last_pub_date - epoch).days + intercept
    last_cutoff = epoch + timedelta(days=int(last_cutoff_days))
    
    # Check if already reached
    if last_cutoff >= submission_date:
        return {
            'status': 'current',
            'message': 'Your application date has already been reached (based on historical trend)!',
            'estimated_date': None,
            'months_to_wait': 0,
        }
    
    # Project when submission_date will be reached
    projected_pub_days = (submission_days - intercept) / slope
    projected_date = epoch + timedelta(days=int(projected_pub_days))
    
    # Calculate months from now
    months_to_wait = calculate_months_between(last_pub_date, projected_date)
    
    if months_to_wait < 0:
        months_to_wait = 0
    
    # Calculate average progress rate for display
    # Slope is in (cutoff_days / pub_days), approximate as days_per_month
    days_per_month = slope * 30  # Rough approximation
    
    return {
        'status': 'projected_historical',
        'message': f'Estimated processing in {int(months_to_wait)} months (based on long-term trend)',
        'estimated_date': projected_date,
        'months_to_wait': int(months_to_wait),
        'avg_progress_days_per_month': round(days_per_month, 1),
        'method': 'historical_regression',
    }

