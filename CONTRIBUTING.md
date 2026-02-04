# Contributing to Telegram CLI

Thank you for your interest in contributing! This document provides guidelines for contributing to the project.

## Getting Started

1. Fork the repository
2. Clone your fork:
   ```bash
   git clone https://github.com/YOUR_USERNAME/Telegram-CLI.git
   cd Telegram-CLI
   ```
3. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```
4. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Development Guidelines

### Code Style

- Follow PEP 8 style guidelines
- Use type hints for function parameters and return values
- Add docstrings to all public functions and classes
- Keep lines under 100 characters

### Commit Messages

- Use clear, descriptive commit messages
- Start with a verb in present tense (e.g., "Add", "Fix", "Update")
- Reference issue numbers when applicable (e.g., "Fix #123")

### Testing

Before submitting a PR:

1. Ensure the code compiles without errors:
   ```bash
   python -m py_compile telegram_forwarder/*.py
   ```

2. Test your changes manually with a test Telegram account

### Pull Requests

1. Create a new branch for your feature/fix:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. Make your changes and commit them

3. Push to your fork:
   ```bash
   git push origin feature/your-feature-name
   ```

4. Open a Pull Request against the `main` branch

5. Fill out the PR template with details about your changes

## Reporting Issues

When reporting bugs, please include:

- Python version (`python --version`)
- Telethon version (`pip show telethon`)
- Operating system
- Steps to reproduce the issue
- Expected vs actual behavior
- Any error messages or logs

## Feature Requests

Feature requests are welcome! Please:

- Check if the feature has already been requested
- Provide a clear description of the feature
- Explain why it would be useful

## Security

If you discover a security vulnerability, please do NOT open a public issue. Instead, contact the maintainer directly.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
