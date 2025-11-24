import logging

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger("weather")


class SummarizeForecastAPIView(APIView):
    """
    Summarize forecast text using simple extraction if over character limit.
    POST params:
      - text: string (required)
      - max_length: int (default 150)
    """

    def post(self, request):
        text = request.data.get("text", "").strip()
        max_length = int(request.data.get("max_length", 120))

        if not text:
            return Response(
                {"error": "text is required"}, status=status.HTTP_400_BAD_REQUEST
            )

        if len(text) <= max_length:
            return Response({"summary": text}, status=status.HTTP_200_OK)

        try:
            # Simple extractive summarization: prioritize first sentences
            summary = self._simple_summarize(text, max_length)
            return Response({"summary": summary}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Summarization error: {e}")
            return Response(
                {"error": "Summarization failed"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def _simple_summarize(self, text, max_length):
        """
        Create a concise summary by extracting key weather information.
        Prioritizes: condition, temperature, timing, precipitation, wind.
        """
        text_lower = text.lower()

        # Extract key information patterns
        key_phrases = []

        # Weather conditions (prioritize these)
        conditions = [
            "sunny",
            "cloudy",
            "rain",
            "snow",
            "thunderstorm",
            "clear",
            "fog",
            "haze",
            "drizzle",
            "showers",
            "storm",
            "wind",
            "chance",
            "partly",
            "mostly",
            "scattered",
        ]
        for cond in conditions:
            if cond in text_lower:
                # Find the sentence or phrase containing this condition
                sentences = text.split(".")
                for sent in sentences:
                    if cond in sent.lower():
                        clean_sent = sent.strip()
                        if clean_sent and clean_sent not in key_phrases:
                            key_phrases.append(clean_sent)
                        break

        # If we found key phrases, build summary from them
        if key_phrases:
            summary = ". ".join(key_phrases)
            if len(summary) <= max_length:
                return summary + "." if not summary.endswith(".") else summary
            # If still too long, take first phrase that fits
            for phrase in key_phrases:
                if len(phrase) <= max_length:
                    return phrase + "." if not phrase.endswith(".") else phrase

        # Fallback: extract first complete sentences within limit
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
            if len(summary) + len(sentence) + 1 <= max_length:
                summary += (" " if summary else "") + sentence
            else:
                break

        # If no complete sentence fits, intelligently truncate at word boundary
        if not summary and sentences:
            first_sent = sentences[0]
            if len(first_sent) > max_length:
                # Find last complete word before max_length
                truncated = first_sent[: max_length - 3]
                last_space = truncated.rfind(" ")
                if last_space > max_length * 0.7:  # At least 70% of text
                    summary = truncated[:last_space] + "..."
                else:
                    summary = truncated + "..."
            else:
                summary = first_sent

        return summary.strip()
