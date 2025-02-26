# Deployment Assistant

Deployment Assistant is an AI-powered search and query agent designed to help you quickly answer deployment-related questions by retrieving and processing content from various sources such as documentation indices, logs, and more. The agent leverages Azure Cognitive Search to index your data and OpenAI's GPT-4 to generate natural language responses based on the provided context.

> **Note:** This project is a work in progress. Some features may be incomplete or subject to change.

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Installation](#installation)
- [Setup Instructions](#setup-instructions)
- [Running the Agent](#running-the-agent)
- [License](#license)

## Overview

Deployment Assistant is designed to assist with deployment-related queries by:
- Indexing documents from various sources.
- Querying across multiple Azure Cognitive Search indices.
- Generating natural language responses using GPT-4.

The long-term vision is to eventually feed the agent data from URLs, team group chats, logs, ICM tickets, etc., so it can provide detailed, context-aware answers.

## Features

- **Multi-Source Search:** Aggregates context from multiple indices to provide detailed answers.
- **GPT-4 Integration:** Uses OpenAI's GPT-4 to generate natural language responses.
- **Environment-Based Configuration:** Sensitive configuration values (API keys, endpoints, etc.) are managed via environment variables.
- **Automated Package Setup:** Uses a custom Python setup script to install required packages globally and update your system PATH (without using virtual environments).

## Installation

### 1. Clone the Repository

Open your terminal and run:

```bash
git clone https://github.com/yourusername/deployment-assistant.git
cd deployment-assistant
```