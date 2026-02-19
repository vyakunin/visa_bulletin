
import os

file_path = 'webapp/templates/webapp/dashboard.html'

with open(file_path, 'r') as f:
    lines = f.readlines()

new_lines = []
skip_next = False
skip_next2 = False

for i in range(len(lines)):
    if skip_next:
        skip_next = False
        continue
    if skip_next2:
        skip_next2 = False
        continue

    line = lines[i]

    # Fix 1: value==
    if 'value==' in line:
        line = line.replace('value==', 'value == ')

    # Fix 2: Multi-line if (lines 132-133 approx)
    # 132: {% if projection.status == 'projected' or projection.status ==
    # 133: 'projected_historical' %}
    if "{% if projection.status == 'projected' or projection.status ==" in line.strip():
        # Combine with next line
        next_line = lines[i+1].strip()
        combined = line.rstrip() + " " + next_line + "\n"
        # Remove extra spaces inside the tag if needed, but simple join is likely enough
        # The split was:
        # ... status ==\n
        # 'projected_historical' %}
        # Result: ... status == 'projected_historical' %}
        # We need to make sure we don't duplicate spaces weirdly but one space is fine.
        new_lines.append(combined)
        skip_next = True
        continue

    # Fix 3: Multi-line variable (lines 134-136 approx)
    # 134: Est. {{ projection.estimated_date|date:"F Y" }} <span
    # 135: class="text-muted small">({{
    # 136: projection.avg_progress_days_per_month|floatformat:1 }} days/mo)</span>
    if 'Est. {{ projection.estimated_date|date:"F Y" }} <span' in line.strip():
        # This one spanned 3 lines in the view I saw.
        # Line 134 ends with <span
        # Line 135 is class="text-muted small">({{
        # Line 136 is projection... }} days/mo)</span>
        
        # NOTE: logic to detect exact lines might be brittle if line numbers shifted.
        # But let's look at the content.
        
        # Actually, let's just make it single line if we find the start.
        if i + 2 < len(lines):
            l2 = lines[i+1].strip()
            l3 = lines[i+2].strip()
            if 'class="text-muted small">({{' in l2 and 'projection.avg_progress_days_per_month' in l3:
                combined = line.strip() + " " + l2 + " " + l3 + "\n"
                new_lines.append(combined)
                skip_next = True # Skip 135
                skip_next2 = True # Skip 136
                continue

    new_lines.append(line)

with open(file_path, 'w') as f:
    f.writelines(new_lines)

print(f"Fixed {file_path}")
