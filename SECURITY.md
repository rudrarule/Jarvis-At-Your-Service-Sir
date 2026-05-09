# Security Policy

## Reporting Security Vulnerabilities

If you discover a security vulnerability in J.A.R.V.I.S, please report it responsibly by **emailing security concerns directly** rather than using the public issue tracker.

### How to Report

1. **Do not** create a public GitHub issue for security vulnerabilities
2. **Contact** the project maintainer at: [You can add your email here or indicate how to contact you]
3. **Include** the following details:
   - Description of the vulnerability
   - Steps to reproduce (if applicable)
   - Potential impact
   - Suggested fix (if you have one)

### Response Timeline

- **Initial response**: Within 48 hours
- **Patch release**: As soon as possible (typically within 7-14 days depending on severity)
- **Public disclosure**: After a patch is available

## Security Considerations

### For Users

Before deploying J.A.R.V.I.S, ensure:

1. **Environment Variables**
   - Never commit `.env` files to version control
   - Use `.env.example` as a template with placeholder values only
   - Rotate API keys regularly

2. **API Keys & Credentials**
   - Treat all API keys (OpenAI, Google, AWS) as secrets
   - Use environment variables or secure credential management tools
   - Never hardcode credentials in source code

3. **WhatsApp Integration**
   - Auth state (`auth_state/`) is stored locally and should not be shared
   - Phone numbers in `APPROVED_CONTACTS` should be carefully curated
   - Consider rate limiting for auto-replies

4. **Data Storage**
   - ChromaDB data (`chroma_data/`) contains conversation history
   - Ensure proper file permissions on local deployments
   - Consider encryption for sensitive installations

5. **Network Security**
   - The FastAPI backend should not be exposed to the public internet without authentication
   - Use HTTPS/SSL in production
   - Implement proper CORS policies for frontend connections

### For Developers

1. **Dependency Management**
   - Keep dependencies updated for security patches
   - Review `requirements.txt` and `package.json` regularly
   - Use vulnerability scanning tools (e.g., `npm audit`, `pip-audit`)

2. **Code Review**
   - All pull requests should be reviewed before merging
   - Pay special attention to changes involving:
     - Environment variable handling
     - API key usage
     - File system operations
     - External API calls

3. **Secrets Scanning**
   - This repository uses automated secret scanning
   - If credentials are accidentally committed, they should be rotated immediately
   - Use tools like `git-secrets` or `pre-commit` hooks locally

## Known Limitations

1. **Local LLM Dependencies**
   - Ollama must be running locally for default operation
   - Some features degrade gracefully if Ollama is unavailable

2. **WhatsApp Integration**
   - Baileys connector is unofficial and may break if WhatsApp changes their protocol
   - Auth tokens should be treated as sensitive credentials

3. **Multi-user Deployments**
   - This project is designed for single-user or trusted environments
   - No built-in user authentication or authorization
   - Not recommended for public-facing deployments without additional security layers

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| Latest  | ✅ Yes             |
| Older   | Security patches only when feasible |

## Additional Security Resources

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [Node.js Security Best Practices](https://nodejs.org/en/docs/guides/security/)
- [Python Security Best Practices](https://python.readthedocs.io/en/stable/library/security_warnings.html)

---

Thank you for helping keep J.A.R.V.I.S secure! 🔒
