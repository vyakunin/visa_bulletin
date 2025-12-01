# Contributing Guide

## Development Workflow

### Setting Up Your Environment

1. Run the setup script:
```bash
./setup.sh
```

2. Activate the virtual environment:
```bash
source ~/visa-bulletin-venv/bin/activate
```

### Running Tests

Before making changes, ensure all tests pass:

```bash
python -m unittest discover -s tests -v
```

### Making Changes

1. Create a new branch for your feature/fix:
```bash
git checkout -b feature-name
```

2. Make your changes to the code

3. Write tests for new functionality in `tests/`

4. Run tests to verify everything works:
```bash
python -m unittest discover -s tests -v
```

5. Commit your changes (tests will run automatically):
```bash
git add .
git commit -m "Description of changes"
```

The pre-commit hook will automatically:
- Run all tests
- Prevent commit if tests fail
- Show which tests failed and why

### Pre-Commit Hook

The `.git/hooks/pre-commit` script runs automatically before each commit and:
- Activates the virtual environment
- Runs the full test suite
- Blocks the commit if any tests fail

To bypass the hook (not recommended):
```bash
git commit --no-verify
```

### Testing Guidelines

- All new features should include tests
- Tests should be placed in the `tests/` directory
- Test files should start with `test_`
- Use descriptive test method names
- Include docstrings explaining what each test validates

### Code Quality

- Follow PEP 8 style guidelines
- Add comments for complex logic
- Update README.md for user-facing changes
- Update CONTRIBUTING.md for developer-facing changes

## Test Structure

```
tests/
├── __init__.py          # Package initializer
└── test_parser.py       # Parser functionality tests
```

### Adding New Tests

1. Create a new test file in `tests/` (e.g., `test_feature.py`)
2. Import unittest and the code you're testing
3. Create a test class inheriting from `unittest.TestCase`
4. Write test methods starting with `test_`
5. Run tests to verify they pass

Example:
```python
import unittest
from lib.your_module import your_function

class TestYourFeature(unittest.TestCase):
    def test_something(self):
        """Test that something works correctly"""
        result = your_function()
        self.assertEqual(result, expected_value)
```

## Questions?

If you encounter issues or have questions, please check:
1. README.md for general usage
2. This CONTRIBUTING.md for development guidelines
3. Existing tests for examples

