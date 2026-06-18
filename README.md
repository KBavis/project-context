# Contextualized 🧠

An AI-powered tool that provides engineering teams with instant, context-aware answers pulled directly from their own codebase, issue trackers, and documentation. Contextualized accelerates development and enhances team productivity by turning your organization's knowledge into an interactive, agentic workflow.

## 🚀 Key Features

- **Agentic Retrieval Workflow**: Uses autonomous agents to intelligently search and retrieve the most relevant information across your connected data sources.
- **Automated Repository Synchronization**: Continuously ingests and chunks code from Git repositories to keep the semantic search index up-to-date.
- **Deep Documentation Integration**: Parses and semantically chunks documentation using advanced AI tools (like Docling) to retain structural context.
- **Multi-Provider Support**: 
  - **Repositories**: GitHub, Bitbucket Server / Data Center
  - **Documentation**: Confluence Server / Data Center
  - **Issue Trackers**: Jira
- **Local & Cloud LLMs**: Out-of-the-box support for both localized models (via Ollama & HuggingFace) for maximum privacy, as well as Cloud LLMs (OpenAI).

## 🏗️ Architecture & Tech Stack

Contextualized is built as a modern monorepo to ensure tight integration between the UI and the synchronization engine.

- **Backend (`apps/backend`)**: 
  - Python / FastAPI
  - **LLM Orchestration**: LlamaIndex, Docling
  - **Database**: PostgreSQL (Relational/Metadata Storage) + asyncpg
  - **Vector Store**: ChromaDB (Embeddings & Semantic Search)
- **Frontend (`apps/frontend`)**: 
  - React / Next.js (or Vite)
- **Deployment (`docker/`)**: 
  - Containerized with Docker Compose for seamless localized setup.

## 📂 Repository Structure

```text
contextualized/
├── apps/
│   ├── backend/      # Python FastAPI application, ingestion pipelines, agents
│   └── frontend/     # React web application for the UI
├── docker/           # Dockerfiles and configuration for containerized services
├── docs/             # (Coming Soon) Detailed architectural and API documentation
├── compose.yaml      # Production Docker Compose stack
└── compose.dev.yaml  # Development Docker Compose stack
```

## 🛠️ Getting Started

1. **Environment Configuration**: 
   - Navigate to `apps/backend/` and copy `.env.sample` to `.env`.
   - Fill in your corresponding secrets for Postgres, ChromaDB, and Data Providers (GitHub, Bitbucket, Confluence, etc.).
2. **Start the Infrastructure**: 
   - Run the application via Docker Compose from the root directory:
     ```bash
     docker compose up -d
     ```
3. **Access the Application**:
   - The API will be available at `http://localhost:8000`
   - The Frontend will be available at `http://localhost:3000` (or specified port).

*For a much more detailed breakdown of internal modules, architecture decisions, and workflow graphs, please refer to the `docs/` folder (Coming Soon).*
