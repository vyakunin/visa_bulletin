
import os

file_path = 'webapp/templates/webapp/dashboard.html'

with open(file_path, 'r') as f:
    content = f.read()

# Fix 1: Add spaces around ==
new_content = content.replace('value==', 'value == ')

# Fix 2: Fix chartData assignment
# value== replacment might affect other things, but here it looks safe for "value=="
# The chart data block:
old_block = """            var chartData = {{ chart_data.chart_json| safe
        }
    };"""
    
new_block = """            var chartData = {{ chart_data.chart_json| safe }};"""

# Try to find the block handling potential variations in whitespace if previous edits partially worked
# But since file looks unchanged, exact match should work.
if old_block in new_content:
    new_content = new_content.replace(old_block, new_block)

# Fix 3: Fix split if tag
old_split = """                                        {% if projection.status == 'projected' or projection.status ==
                                        'projected_historical' %}"""
new_split = """                                        {% if projection.status == 'projected' or projection.status == 'projected_historical' %}"""

if old_split in new_content:
    new_content = new_content.replace(old_split, new_split)
else:
    # Try normalized split replacement if indentation varies slightly
    print("Exact split match failed. Attempting generalized join.")
    # This specifically targets the "projection.status ==" line break
    new_content = new_content.replace("projection.status ==\n                                        'projected_historical' %}", "projection.status == 'projected_historical' %}")


with open(file_path, 'w') as f:
    f.write(new_content)

print("Successfully updated dashboard.html")
