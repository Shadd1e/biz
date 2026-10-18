import json
import httpx
from .config import settings

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"


async def _chat(payload: dict) -> dict:
    if not settings.deepseek_api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is not configured")
    headers = {
        "Authorization": f"Bearer {settings.deepseek_api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=25) as client:
        response = await client.post(DEEPSEEK_URL, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()


async def explain_recommendation(movie: dict, signals: dict) -> str | None:
    if not settings.deepseek_api_key:
        return None

    prompt = f"""Write one warm, natural sentence explaining why this movie may suit the user.
Do not mention algorithms, scores, AI, databases, or 'based on your preferences'.
Do not invent facts. Use only the supplied movie facts and recommendation signals.
Avoid sales language and avoid sounding like a system notification.
Movie: {movie.get('title')}
Genres: {', '.join(movie.get('genres') or [])}
Overview: {movie.get('overview') or ''}
Signals: {json.dumps(signals)}
"""
    payload = {
        "model": settings.deepseek_model,
        "messages": [
            {
                "role": "system",
                "content": "You write concise, human-sounding movie recommendation reasons for older adults. Be respectful and specific.",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 90,
    }
    try:
        data = await _chat(payload)
        return data["choices"][0]["message"]["content"].strip()
    except Exception:
        return None


async def recommend_movies_with_deepseek(
    genres: list[str],
    favourite_titles: list[str] | None = None,
    rated_titles: list[str] | None = None,
    limit: int = 12,
) -> list[dict]:
    """Emergency recommendation source used when the local movie catalogue is empty.

    DeepSeek returns movie titles and enough descriptive data for the UI to render a
    recommendation even when the movie-data provider is unavailable. The backend can
    subsequently enrich these records with TMDB when that service is available.
    """
    if not settings.deepseek_api_key:
        return []

    favourite_titles = favourite_titles or []
    rated_titles = rated_titles or []
    genre_text = ", ".join(genres) if genres else "general audience-friendly films"

    prompt = f"""Recommend exactly {max(1, min(limit, 12))} real movies for a user.

Preferred genres: {genre_text}
Favourite movies already selected: {', '.join(favourite_titles) or 'none'}
Movies already rated/seen: {', '.join(rated_titles) or 'none'}

Choose real, well-known movies. Do not invent movie titles. Avoid movies in the already
selected/rated lists. Prioritize strong matches to the stated genres and give variety.
Return ONLY valid JSON with this shape:
{{
  "recommendations": [
    {{
      "title": "Movie title",
      "release_year": 2020,
      "genres": ["Drama"],
      "overview": "A short factual synopsis.",
      "reason": "A short, natural reason this is a good match."
    }}
  ]
}}
"""

    payload = {
        "model": settings.deepseek_model,
        "messages": [
            {
                "role": "system",
                "content": "You are a movie recommendation engine. Recommend real movies and never fabricate titles. Return valid JSON only.",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.35,
        "max_tokens": 1800,
        "response_format": {"type": "json_object"},
    }

    try:
        data = await _chat(payload)
        content = data["choices"][0]["message"].get("content") or "{}"
        parsed = json.loads(content)
        recommendations = parsed.get("recommendations", [])
        if not isinstance(recommendations, list):
            return []

        results = []
        seen = set()
        for item in recommendations:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            if not title or title.lower() in seen:
                continue
            seen.add(title.lower())
            year = item.get("release_year")
            genres_out = item.get("genres") if isinstance(item.get("genres"), list) else []
            overview = str(item.get("overview") or "").strip()
            reason = str(item.get("reason") or "").strip()
            results.append(
                {
                    "id": None,
                    "title": title,
                    "release_date": f"{int(year):04d}-01-01" if isinstance(year, int) and 1800 <= year <= 2100 else None,
                    "genres": [str(g) for g in genres_out[:6]],
                    "overview": overview,
                    "cast": [],
                    "director": None,
                    "keywords": [],
                    "poster_path": None,
                    "source": "deepseek",
                    "deepseek_reason": reason,
                }
            )
            if len(results) >= limit:
                break
        return results
    except Exception:
        return []


async def interpret_preference(request: str) -> dict:
    if not settings.deepseek_api_key:
        return {"genres": [], "keywords": [], "mood": None}
    tools = [{
        "type": "function",
        "function": {
            "name": "extract_movie_preferences",
            "description": "Extract structured movie preferences from a natural-language request.",
            "parameters": {
                "type": "object",
                "properties": {
                    "genres": {"type": "array", "items": {"type": "string"}},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                    "mood": {"type": ["string", "null"]},
                },
                "required": ["genres", "keywords", "mood"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    }]
    payload = {
        "model": settings.deepseek_model,
        "messages": [
            {"role": "system", "content": "Extract movie preferences. Do not infer sensitive personal traits."},
            {"role": "user", "content": request},
        ],
        "tools": tools,
        "tool_choice": {"type": "function", "function": {"name": "extract_movie_preferences"}},
        "temperature": 0,
    }
    try:
        data = await _chat(payload)
        call = data["choices"][0]["message"]["tool_calls"][0]
        return json.loads(call["function"]["arguments"])
    except Exception:
        return {"genres": [], "keywords": [], "mood": None}
