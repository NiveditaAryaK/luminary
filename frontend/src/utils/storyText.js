export function stripChoiceMarkup(text) {
  if (!text) return ''

  return text
    .replace(/CHOICE_[A-C]\s*:\s*([\s\S]*?)(?=CHOICE_[A-C]\s*:|$)/gi, '')
    .replace(/^\s*Choice\s*[A-C]\s*:\s*.+$/gim, '')
    .replace(/^\s*[1-3]\.\s*.+$/gim, '')
    .trim()
}
