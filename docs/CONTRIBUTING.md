# Contributing to mos-gis

Thank you for your interest in contributing to mos-gis! We welcome contributions from the community.

## How to Contribute

### Reporting Issues

If you find a bug or have a feature request:

1. **Search existing issues** to avoid duplicates
2. **Create a new issue** with a clear title and description
3. **Include relevant details**:
   - Steps to reproduce (for bugs)
   - Expected vs actual behavior
   - Environment details (OS, Docker version, etc.)
   - Sample data or error messages

### Submitting Changes

#### 1. Fork and Clone

```bash
# Fork the repository on GitHub, then:
git clone https://github.com/YOUR_USERNAME/mos-gis.git
cd mos-gis
git remote add upstream https://github.com/Mon-Systeme-Fourrager/mos-gis.git
```

#### 2. Create a Branch

We follow **Git Flow** branching:

- **`develop`** - Main development branch
- **`main`** - Production releases
- **`feature/*`** - New features (from `develop`)
- **`bugfix/*`** - Bug fixes (from `develop`)

```bash
# Update your fork
git checkout develop
git pull upstream develop

# Create your branch
git checkout -b feature/your-feature-name
# or
git checkout -b bugfix/issue-description
```

#### 3. Make Your Changes

- Write clear, documented code
- Follow existing code style and conventions
- Add tests for new functionality
- Update documentation as needed

#### 4. Test Your Changes

```bash
# Run tests
docker compose run --rm tests

# Run specific tests
docker compose run --rm tests pytest gis-pipeline/test/

# Check code coverage
docker compose run --rm tests pytest --cov=gis_pipeline
```

#### 5. Commit and Push

```bash
# Stage your changes
git add .

# Commit with a clear message
git commit -m "feat: add new processing feature"
# or
git commit -m "fix: resolve projection issue in pipeline"

# Push to your fork
git push origin feature/your-feature-name
```

**Commit message format:**
- `feat:` New feature
- `fix:` Bug fix
- `docs:` Documentation changes
- `test:` Test additions/changes
- `refactor:` Code refactoring
- `chore:` Maintenance tasks

#### 6. Open a Pull Request

1. Go to the [mos-gis repository](https://github.com/Mon-Systeme-Fourrager/mos-gis)
2. Click **"New Pull Request"**
3. Select `develop` as the base branch
4. Provide a clear title and description:
   - What changes were made
   - Why they were necessary
   - Any breaking changes or migration notes
5. Link related issues (e.g., "Closes #123")

### Code Review Process

- Maintainers will review your PR
- Address any feedback or requested changes
- Once approved, your PR will be merged into `develop`

## Development Setup

See the main [README](../README.md) for:
- Installation instructions
- Docker setup
- Running services locally
- Pipeline usage

For technical details, see:
- **[Technical Documentation](../gis-pipeline/docs/TECHNICAL_DOCUMENTATION.md)**
- **[CLI Arguments](../gis-pipeline/docs/ARGS.md)**

## Code Style

- Follow PEP 8 for Python code
- Use type hints where appropriate
- Write docstrings for functions and classes
- Keep functions focused and modular

## Testing Guidelines

- Write unit tests for new features
- Ensure tests pass before submitting PR
- Aim for good code coverage
- Test edge cases and error handling

## Getting Help

- Check existing [documentation](../docs/)
- Review [issues](https://github.com/Mon-Systeme-Fourrager/mos-gis/issues)
- Ask questions in issue discussions

## Recognition

Contributors will be recognized in release notes and project documentation.

Thank you for helping improve mos-gis!
