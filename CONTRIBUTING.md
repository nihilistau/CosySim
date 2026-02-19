# Contributing to CosyVoice

Thank you for your interest in contributing! This document provides guidelines for contributing to this project.

## Getting Started

1. Fork the repository
2. Clone your fork: `git clone https://github.com/your-username/CosyVoice.git`
3. Create a new branch: `git checkout -b feature/your-feature-name`
4. Make your changes
5. Test your changes
6. Commit with clear messages
7. Push to your fork
8. Open a Pull Request

## Development Setup

See [INSTALL.ps1](INSTALL.ps1) for installation instructions.

```powershell
# Install dependencies
pip install -r requirements.txt

# Run tests
pytest tests/
```

## Code Style

- Follow PEP 8 for Python code
- Use meaningful variable names
- Add docstrings to functions and classes
- Keep functions focused and concise

## Testing

- Add tests for new features
- Ensure all tests pass before submitting PR
- Run the test suite: `pytest tests/`

## Documentation

- Update relevant .md files when adding features
- Add inline comments for complex logic
- Update README.md if changing setup/usage

## Commit Messages

- Use clear, descriptive commit messages
- Start with a verb (Add, Fix, Update, Remove)
- Reference issues when applicable

Examples:
- `Add support for new audio format`
- `Fix memory leak in TTS processing`
- `Update documentation for API endpoints`

## Pull Request Process

1. Update documentation as needed
2. Add tests for new functionality
3. Ensure all tests pass
4. Update CHANGELOG if applicable
5. Request review from maintainers

## Code of Conduct

Please note we have a [Code of Conduct](CODE_OF_CONDUCT.md), please follow it in all your interactions with the project.

## Questions?

Feel free to open an issue for questions or discussions.
