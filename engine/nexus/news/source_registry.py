"""News source definitions and curated question sets."""
from __future__ import annotations
import logging
from typing import Dict, List

logger = logging.getLogger(__name__)

NEWS_SOURCES: Dict[str, List[Dict]] = {
    "ai_research": [
        {"name": "Hugging Face Blog", "rss": "https://huggingface.co/blog/feed.xml"},
        {"name": "Google AI Blog", "rss": "https://blog.google/technology/ai/rss"},
        {"name": "OpenAI News", "rss": "https://openai.com/blog/rss.xml"},
        {"name": "Towards Data Science", "rss": "https://towardsdatascience.com/feed"},
        {"name": "The Batch", "rss": "https://read.deeplearning.ai/the-batch/rss"},
    ],
    "tech": [
        {"name": "Hacker News", "rss": "https://hnrss.org/frontpage"},
        {"name": "Ars Technica", "rss": "https://feeds.arstechnica.com/arstechnica/technology-lab"},
        {"name": "The Verge", "rss": "https://www.theverge.com/rss/index.xml"},
    ],
    "world": [
        {"name": "Reuters", "rss": "https://feeds.reuters.com/reuters/topNews"},
        {"name": "BBC World", "rss": "http://feeds.bbci.co.uk/news/world/rss.xml"},
    ],
    "science": [
        {"name": "Phys.org", "rss": "https://phys.org/rss-feed/"},
        {"name": "New Scientist", "rss": "https://www.newscientist.com/feed/home/"},
    ],
}

CURATED_QUESTIONS: Dict[str, List[str]] = {
    "ai_research": [
        "What are the most significant AI research findings reported today?",
        "Which papers or announcements could change how we build AI systems?",
        "What are the key technical claims and are there limitations or caveats mentioned?",
        "Which organisations are leading today's AI developments?",
        "What should a developer building with LLMs know from today's news?",
        "Are there any safety, ethics, or policy developments worth noting?",
        "What open-source models or tools were announced or released?",
        "What benchmarks or evaluations were published?",
        "What is the overall sentiment — optimistic, cautious, or concerning?",
        "Summarise today's AI news in 5 bullet points.",
    ],
    "tech": [
        "What are the biggest tech stories today?",
        "What developer tools, frameworks, or platforms were announced?",
        "What security or privacy issues were reported?",
        "What infrastructure or cloud developments were notable?",
        "Summarise today's tech news in 5 bullet points.",
    ],
    "world": [
        "What are the most significant global events today?",
        "Are there any economic developments that could affect technology sectors?",
        "What geopolitical events might affect international AI development?",
        "Summarise today's world news in 5 bullet points.",
    ],
    "science": [
        "What are the most important scientific breakthroughs reported today?",
        "Are there any findings relevant to AI or computing?",
        "What medical or biological discoveries were announced?",
        "Summarise today's science news in 5 bullet points.",
    ],
}


def get_sources(category: str) -> List[Dict]:
    return NEWS_SOURCES.get(category, [])


def get_questions(category: str) -> List[str]:
    return CURATED_QUESTIONS.get(category, CURATED_QUESTIONS["tech"])


def get_all_categories() -> List[str]:
    return list(NEWS_SOURCES.keys())
