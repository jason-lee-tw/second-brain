# “Second Brain” Capstone Assignment

## Overview

Build a "second brain" system for your own personal use, using evaluation-driven development.

## Requirements

Design a multi-agent system that ingests data from various sources, stores information (notes, meeting transcriptions, your own cooking recipes or anything you want!) for semantic retrieval, and maintains persistent memory of conversations and user preferences.
The system should demonstrate measurable improvement over basic chatbots through rigorous evaluation. Include at least three specialized agents that work together to research, synthesize information, and learn from interactions. Provide a simple interface for you to interact with your second brain and show clear evidence through your evaluation metrics if multi-agent architecture, RAG implementation, or memory systems provide concrete benefits over simpler approaches.

## In Scope

- Use LangGraph.
- Use Eval Driven Development. AI output must be evaluated.
- Implement OTEL observability
- Implement RAG for Content (notes, meeting transcriptions etc.)
- Implement basic Memory
- Add Guardrail to remove PII in memory/message history.
- Store data locally
- Optional: Use MCP servers for some of the functionality.
- Optional: Recommended to implement multi agent orchestration using any multi agent pattern

## Out of Scope

- Large scale web scraping or document ingestion
- Cloud hosting
- Exposing anything to the internet
- Really nice looking GUI
- Complicated observability setup

## Suggested Data Source for Your Second Brain

To help you build a richer and more useful Second Brain, you are encouraged to ingest meaningful, real-world content.

## Models

Learners can choose to use either Claude or Gemini models (if the 5$ credit has not been exhausted) to do the Capstone project. We recommend the learner to try it out in both and see how each of the models perform.

## Tech Stack

- Python
- LangGraph
- Postgres Vector
- Arize Phoenix (with Postgres)
- Docker (docker compose)
- Tavily SDK (for web search, web crawling and extract data on website)
