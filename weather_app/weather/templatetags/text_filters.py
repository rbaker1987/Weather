from django import template

register = template.Library()


@register.filter
def truncate_smart(text, max_length=120):
    """Truncate text to max_length, trying to break at sentence boundaries or word boundaries."""
    if not text or len(text) <= max_length:
        return text

    # Try to break at sentence boundaries
    sentences = []
    current = ""
    for char in text:
        current += char
        if char in ".!?" and len(current.strip()) > 0:
            sentences.append(current.strip())
            current = ""
    if current.strip():
        sentences.append(current.strip())

    # Build summary from first sentences that fit
    summary = ""
    for sentence in sentences:
        test_length = len(summary) + (1 if summary else 0) + len(sentence)
        if test_length <= max_length:
            summary += (" " if summary else "") + sentence
        else:
            break

    # If we got at least one complete sentence, use it
    if summary and len(summary) < len(text):
        return summary

    # Otherwise, truncate at word boundary
    if len(text) <= max_length:
        return text

    # Find last space before max_length
    truncated = text[:max_length]
    last_space = truncated.rfind(" ")

    if last_space > max_length * 0.8:  # Only use word boundary if it's reasonable
        return truncated[:last_space].strip() + "..."
    return truncated.strip() + "..."
