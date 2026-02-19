#!/bin/bash
months=(
    "2026-05" "2026-04" "2026-03" "2026-02" "2026-01"
    "2025-12" "2025-11" "2025-10" "2025-09" "2025-08" "2025-07" "2025-06"
)

for m in "${months[@]}"; do
    # Fetch page
    content=$(curl -s "http://127.0.0.1:8000/predictions/$m/")
    
    # Extract Title (Predictions for ...)
    title=$(echo "$content" | grep -o "Predictions for [A-Z][a-z]* [0-9]*" | head -n 1)
    
    # Extract Knowledge Date
    kdate=$(echo "$content" | grep -o "Knowledge Date: [A-Z][a-z]* [0-9]*, [0-9]*")
    
    if [ -z "$title" ]; then
        echo "FAILED: $m (No title found)"
    else
        echo "$title"
        echo "$kdate"
    fi
done
