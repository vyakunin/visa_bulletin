# Future Features Documentation

This directory contains design documents for features that are planned but not yet implemented.

## Overview

These documents represent well-researched feature proposals that may be implemented in the future. They are kept separate from current documentation to avoid confusion about what is currently available vs what is planned.

## Documentation Files

### Company Report Card
- **COMPANY_REPORT_CARD_DESIGN.md** - Comprehensive design for a company green card sponsorship grading system
  - **What:** A data-driven grading system ranking companies on green card sponsorship friendliness
  - **Value Proposition:** "Glassdoor for Immigration" using objective DOL PERM data
  - **Key Metrics:** Volume, speed, success rates, salary levels
  - **Status:** Design phase, not implemented
  - **Estimated Effort:** 3-4 weeks implementation time
  - **Market Potential:** 150K+ monthly visitors, high PR potential

## When to Implement

Features in this directory should be prioritized based on:
1. **User demand** - How many users are requesting this feature?
2. **Data availability** - Do we have the necessary data?
3. **Implementation complexity** - How much effort is required?
4. **Strategic value** - Does it align with product goals?
5. **Dependencies** - What existing features must be in place first?

## Moving Features Out

When a feature is implemented:
1. Move implementation details to appropriate directory (e.g., `docs/department_of_labor/`)
2. Update the feature design doc to reference the implementation
3. Consider deleting the design doc if fully integrated into other documentation
4. Update `FEATURE_IDEAS.md` in the root docs directory

## Related

- **FEATURE_IDEAS.md** - Shorter feature ideas that may become full design docs
- **docs/department_of_labor/** - Implemented DOL data features
- **docs/ingest/** - Implemented ingest pipeline features

