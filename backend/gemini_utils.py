def format_model_error(exc: Exception) -> str:
    message = str(exc)
    lowered = message.lower()
    if "resource_exhausted" in lowered or "quota" in lowered or "429" in lowered:
        return "Gemini quota exceeded for this API key. Please check billing, limits, or try again later."
    if "api key" in lowered or "permission" in lowered or "unauthorized" in lowered or "403" in lowered:
        return "Gemini request was rejected. Verify GOOGLE_API_KEY and project access."
    if "not_found" in lowered or "no longer available" in lowered or "404" in lowered:
        return "The configured Gemini model is unavailable. Update the backend model configuration."
    return "Gemini request failed. Please verify your model access and try again."
