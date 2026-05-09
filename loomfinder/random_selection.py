import random
import re

from .categories import literature_genres, default_genres_subjects

# Minimum ratio of "real" words (mostly alphabetic) to accept a segment
MIN_WORD_QUALITY = 0.5


def _is_real_word(word):
    """A word counts as real if ≥60% of its characters are letters."""
    if not word:
        return False
    letters = sum(1 for c in word if c.isalpha())
    return letters / len(word) >= 0.6


def segment_quality(text):
    """Return ratio of real words in text (0.0 – 1.0)."""
    words = re.findall(r"\S+", text)
    if not words:
        return 0.0
    return sum(1 for w in words if _is_real_word(w)) / len(words)


def extract_segment(text, num_words=200, min_quality=MIN_WORD_QUALITY, num_candidates=15):
    words = re.findall(r"\S+", text)
    if len(words) < num_words:
        return None

    candidates = []
    for _ in range(num_candidates):
        start = random.randint(0, len(words) - num_words)
        segment = words[start:start + num_words]

        end = start + num_words
        while end < len(words) and not words[end].endswith("."):
            segment.append(words[end])
            end += 1

        candidate = " ".join(segment)
        quality = segment_quality(candidate)
        candidates.append((quality, candidate))

    candidates.sort(key=lambda x: x[0], reverse=True)
    best_quality, best_candidate = candidates[0]

    return best_candidate if best_quality >= min_quality else None


def get_weighted_random_choice():
    weights = [
        0.8 if genre in literature_genres else 0.2
        for genre in default_genres_subjects
    ]
    return random.choices(default_genres_subjects, weights=weights, k=1)[0]
