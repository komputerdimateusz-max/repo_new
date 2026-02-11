# AGENT_CODEX.md

## Project
**repo_new** — Meal ordering system for employees in industrial zones  
Roles: Employee, Company, Catering, Admin

This file defines strict instructions and expectations for Codex in this project.

---

## 1) Primary Role of the Agent

You act as a **Senior Developer** collaborator. Your job is to:
1. Understand the brief before coding.
2. Ask clarifying questions if requirements are ambiguous.
3. Generate clean, production-ready code.
4. Write tests where applicable.
5. Produce clear commit messages and small logical commits.

You DO NOT:
- Guess unclear requirements.
- Rewrite entire unrelated modules without approval.
- Introduce unnecessary dependencies.

---

## 2) Coding Standards

### General
- Use **English** for all code, comments, docstrings, and variable names.
- Write code that is easy to read and maintain.
- Prefer explicit over clever/implicit solutions.
- Prioritize correctness and simplicity.

### Python Backend (FastAPI)
- Use type hints everywhere.
- Use Pydantic models for request/response schemas.
- Follow PEP8 formatting.
- Include docstrings and descriptive naming.

### Frontend (Web / PWA)
- Use reusable components and consistent layout.
- Keep UI intuitive and mobile-friendly.
- Maintain consistent styling and layout logic.

---

## 3) Git Workflow Rules

### Branching
- Default branch: `main`
- Features: `feature/<description>`
- Bugfixes: `bugfix/<description>`
- Hotfixes: `hotfix/<description>`

### Commit Message Format

```
<type>(<scope>): <short description>

<body - detailed rationale>
```

Allowed `<type>` values:
- feat — new feature
- fix — bug fix
- docs — documentation
- refactor — structural changes without feature changes
- test — tests added or updated
- chore — maintenance

Examples:
```
feat(auth): add login with hashed passwords
fix(api): correct 400 response on invalid input
docs(readme): update setup instructions
```

- Do not push directly to `main` without approval.
- Always work on a feature branch.

---

## 4) Architecture Guidelines

### Authentication
- Use JWT-based authentication.
- Hash passwords securely (bcrypt or equivalent).
- Clearly separate user roles in the data model.

### Orders
- Enforce cut-off time validation in backend logic.
- Frontend must prevent submission after cut-off.
- Orders must be grouped by date and company.

### Payments
- Integrate BLIK payment flow.
- Do not store payment credentials.
- Log payment attempts and statuses.

### Reporting & Export
- Provide CSV and PDF export endpoints.
- Allow filtering by date and company.

---

## 5) Testing Requirements

### Backend
- Use pytest.
- Cover:
  - endpoints
  - validation logic
  - business rules
- Minimum 70% coverage before feature completion.

### Frontend
- Validate data flow and form logic.
- Ensure responsive behavior.

---

## 6) Documentation Rules

- Update README.md when adding new features.
- Provide API usage examples.
- Maintain CHANGELOG.md for major updates.

---

## 7) Clarification Rule

If requirements are unclear:
- Ask clarifying questions.
- Do not guess business logic.
- Do not implement speculative features.

---

## 8) Task Execution Structure

For each task:
1. Clarify scope.
2. Propose minimal architecture if needed.
3. Implement feature.
4. Add tests.
5. Update documentation.
6. Provide commit message proposal.

---

## 9) Quality Expectations

- Code must be modular.
- Avoid unnecessary dependencies.
- Keep logic separated from presentation.
- Favor readability over cleverness.

---

End of AGENT_CODEX.md
