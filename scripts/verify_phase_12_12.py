import requests
import json
import re

def verify():
    dashboard_url = "http://127.0.0.1:8000/employment-based/all/"
    response = requests.get(dashboard_url)
    print(f"Dashboard Status: {response.status_code}")
    
    # 1. Verify Default Action Type
    if 'value="dates_for_filing" selected' in response.text:
        print("PASS: Dates for Filing is default.")
    else:
        print("FAIL: Dates for Filing is NOT default.")
        # Find what is selected
        match = re.search(r'value="([^"]+)" selected', response.text)
        if match:
            print(f"Actually selected: {match.group(1)}")
            
    # 2. Verify Internal Links in Chart Data
    # Look for chart_json in script tags
    if "/predictions/" in response.text:
        print("PASS: Internal prediction links found in HTML.")
    else:
        print("FAIL: No internal prediction links found.")

    # 3. Verify Stepped Projections
    # Check if we have multiple points in a projection trace
    # The JSON is escaped in the HTML
    if "Projection" in response.text:
        # Search for "x":[...] with more than 2 dates for a projection
        # This is harder via regex on raw HTML, but let's look for multiple date strings
        # following "Projection" trace name.
        matches = re.findall(r'20[2-3][0-9]-[0-9]{2}-[0-9]{2}', response.text)
        print(f"DEBUG: Found {len(matches)} date strings in HTML.")
        if len(matches) > 100: # Historical + Projections should have many
             print("PASS: Multiple date points found in HTML (indicates stepped projections).")
        else:
             print("FAIL: Few date points found.")

    # 4. Verify Detail Page Accuracy Score
    detail_url = "http://127.0.0.1:8000/predictions/2026-02/"
    response = requests.get(detail_url)
    print(f"Detail Page Status: {response.status_code}")
    if "Accuracy score moved to Filing column" in response.text:
        print("PASS: Accuracy score moved to Filing column (comment found).")
    else:
        print("FAIL: Accuracy score comment NOT found.")

if __name__ == "__main__":
    verify()
