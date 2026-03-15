export function parseChoices(text) {
  if (!text) return []

  const direct = []
  const re = /CHOICE_[A-C]\s*:\s*([\s\S]*?)(?=CHOICE_[A-C]\s*:|$)/gi
  let match

  while ((match = re.exec(text)) !== null) {
    const cleaned = match[1].trim().replace(/^[\-\u2022]+/g, '').trim()
    if (cleaned) direct.push(cleaned)
  }

  if (direct.length >= 2) return direct

  const picks = []
  const lines = text.split('\n').map((line) => line.trim()).filter(Boolean)
  const choiceLines = lines.filter((line) => /^CHOICE_[A-C]\s*:/i.test(line))
  const scanLines = choiceLines.length ? choiceLines : lines.slice(-12)

  for (const line of scanLines) {
    const m1 = /^CHOICE_[A-C]\s*:\s*(.+)$/i.exec(line)
    if (m1) {
      picks.push(m1[1])
      continue
    }

    const m2 = /^Choice\s*[A-C]\s*:\s*(.+)$/i.exec(line)
    if (m2) {
      picks.push(m2[1])
      continue
    }

    const m3 = /^[A-C]\.\s*(.+)$/.exec(line)
    if (m3) {
      picks.push(m3[1])
      continue
    }

    const m4 = /^[1-3]\.\s*(.+)$/.exec(line)
    if (m4) {
      picks.push(m4[1])
    }
  }

  return picks.length >= 2 ? picks : []
}
