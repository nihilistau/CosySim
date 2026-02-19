# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability within this project, please send an email to the maintainers. All security vulnerabilities will be promptly addressed.

**Please do not report security vulnerabilities through public GitHub issues.**

## Supported Versions

We release patches for security vulnerabilities for the following versions:

| Version | Supported          |
| ------- | ------------------ |
| main    | :white_check_mark: |

## Security Best Practices

When using this project:

1. **Never commit API keys or tokens** - Use environment variables instead
2. **Keep dependencies updated** - Regularly update requirements.txt
3. **Use .env files** - Copy `.env.example` to `.env` and configure with your keys
4. **Review .gitignore** - Ensure sensitive files are not tracked
5. **Secure your endpoints** - Add authentication if exposing services over network

## Known Security Considerations

- This project is designed for local or trusted network use
- Demo files contain mock API keys for illustration - replace with real credentials in .env
- Audio files may contain voice biometric data - handle according to your privacy policy
