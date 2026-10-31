"""A short lead brief for the CRM comment and the lead profile.

Every lead gets the same five discovery questions plus a playbook chosen from the
recorded lead type (code violation, foreclosure, probate, tax lien, divorce, ...).
The text is assembled locally from recorded facts only; no model call and no invented
price, condition, deadline or legal advice.
"""

from typing import Optional

MAX_BRIEF = 2000

CORE_QUESTIONS = [
    "Motivation: what has you thinking about selling this property now?",
    "Asking price: what number would make you say yes today?",
    "Condition: if I walked it today, what would need work (roof, HVAC, foundation, plumbing)?",
    "Closing timeline: if we agreed on terms, when would you want to close?",
    "Deed: is anyone else on the deed besides you, or does anyone else have a claim?",
]

PLAYBOOKS = {
    "code_violation": {
        "label": "Code violation",
        "angle": "A city code case can carry fines or a compliance deadline; the owner may want a clean exit.",
        "opening": "I saw the code case recorded at {address}. I am not with the city — I buy as-is and take on the repairs.",
        "ask": [
            "What did the notice cite, and is the work still open?",
            "Are there fines, a hearing date, or a deadline to comply?",
            "Have you had a contractor look at the repairs?",
        ],
        "avoid": "Do not imply you can make the case or the fines disappear.",
    },
    "foreclosure": {
        "label": "Foreclosure",
        "angle": "A recorded foreclosure timeline creates urgency; the owner may be able to sell before the sale date.",
        "opening": "I saw the foreclosure notice on {address}. I am not a lawyer and I am not here to give legal advice — I buy as-is if a sale still helps.",
        "ask": [
            "What is the scheduled sale date?",
            "What would it take to reinstate the loan?",
            "Is the property occupied, and by whom?",
        ],
        "avoid": "Do not give legal or tax advice, and do not promise the foreclosure will stop.",
    },
    "inheritance": {
        "label": "Inherited / probate",
        "angle": "An inherited property often has several heirs, a probate step and a house full of contents.",
        "opening": "I understand {address} came through an inheritance. I buy as-is and can work around the probate timeline.",
        "ask": [
            "Has probate been opened, or is the deed already transferred?",
            "Do all the heirs agree on selling?",
            "Is the property occupied, and what is still inside?",
        ],
        "avoid": "Do not push for a decision before the heirs and the personal representative are clear.",
    },
    "tax_lien": {
        "label": "Tax lien",
        "angle": "A tax lien has an amount, a redemption window and a deadline; the owner may be able to sell and clear it.",
        "opening": "I saw the tax lien recorded on {address}. I buy as-is and can coordinate paying it off at closing.",
        "ask": [
            "What is the total owed, and is there a payment plan?",
            "Is there a redemption or sale deadline?",
            "Are there other liens or code cases on the property?",
        ],
        "avoid": "Do not quote a payoff amount you have not verified with the county.",
    },
    "divorce": {
        "label": "Divorce",
        "angle": "A divorce sale needs both owners aligned and a date that fits the settlement.",
        "opening": "I understand this is a difficult time. I buy as-is; I am not asking anyone to take sides.",
        "ask": [
            "Are both owners on the deed and in agreement about selling?",
            "Is there a settlement date or court timeline?",
            "Who is living in the property now?",
        ],
        "avoid": "Do not ask about the reasons for the divorce or discuss either party's position.",
    },
    "lis_pendens": {
        "label": "Lis pendens",
        "angle": "A lis pendens signals a pending legal action; the sale may need the attorney's and lender's cooperation.",
        "opening": "I saw a lis pendens recorded on {address}. I am not a lawyer — I buy as-is and can work with your attorney on timing.",
        "ask": [
            "What is the case about, and is there a hearing date?",
            "Does your attorney see any problem with a sale?",
            "Is the loan current, and what is owed?",
        ],
        "avoid": "Do not interpret the case or promise an outcome.",
    },
    "tax_deed": {
        "label": "Tax deed sale",
        "angle": "A tax deed sale has a statutory date and redemption rules; the owner needs the exact timeline.",
        "opening": "I saw the tax deed sale recorded for {address}. I buy as-is and will work from the recorded dates, not guesses.",
        "ask": [
            "What is the sale date and the redemption deadline?",
            "How much is owed in total?",
            "Has anyone filed to stop the sale?",
        ],
        "avoid": "Do not state a redemption amount or deadline without the county record in front of you.",
    },
    "hoa_lien": {
        "label": "HOA lien",
        "angle": "An HOA lien can grow with fees and a deadline; the owner may want a clean sale.",
        "opening": "I saw the HOA lien on {address}. I buy as-is and can clear it at closing.",
        "ask": [
            "How much is owed, including fees and attorney costs?",
            "Is there a lien sale or deadline?",
            "Are there other violations or assessments?",
        ],
        "avoid": "Do not quote an HOA payoff you have not verified.",
    },
    "general": {
        "label": "General seller",
        "angle": "No special recorded event; the job is to find the real motivation and the condition.",
        "opening": "I am calling about {address}. I buy houses as-is for cash — is selling something you are considering this year?",
        "ask": [
            "What would need to happen for you to be open to selling?",
            "How soon are you hoping to close?",
            "What condition is the property in today?",
        ],
        "avoid": "Do not invent an ARV, repair estimate or offer on the first call.",
    },
}


def _playbook_key(lead) -> str:
    value = f"{lead.lead_type or ''} {lead.source_status or ''}".lower()
    if "code" in value or "violation" in value:
        return "code_violation"
    if "probate" in value or "inherit" in value or "estate" in value:
        return "inheritance"
    if "foreclosure" in value or "pre-foreclosure" in value or "notice of default" in value:
        return "foreclosure"
    if "tax deed" in value:
        return "tax_deed"
    if "hoa" in value:
        return "hoa_lien"
    if "tax lien" in value or "tax" in value and "lien" in value:
        return "tax_lien"
    if "divorce" in value:
        return "divorce"
    if "lis pendens" in value:
        return "lis_pendens"
    return "general"


def _address(lead) -> str:
    prop = lead.properties[0] if lead.properties else None
    if prop is None:
        return "the property"
    parts = [prop.street_address, prop.city, prop.state, prop.zip_code]
    return ", ".join(part for part in parts if part) or "the property"


def _flags(lead) -> list[str]:
    names = []
    for key, value in (lead.ds_flags or {}).items():
        if value:
            names.append(str(key).replace("_", " "))
    names.extend(str(item) for item in (lead.ds_extra_flags or []) if str(item).strip())
    return names[:8]


def build_playbook(lead) -> str:
    """The five questions and the type-specific playbook, without contact/summary fields."""
    key = _playbook_key(lead)
    play = PLAYBOOKS[key]
    address = _address(lead)
    lines = ["", "Ask the lead manager's five questions:"]
    for index, question in enumerate(CORE_QUESTIONS, start=1):
        lines.append(f"{index}. {question}")
    lines.append("")
    lines.append(f"Playbook — {play['label']}:")
    lines.append("Opening: " + play["opening"].format(address=address))
    lines.append("Ask first: " + " ".join(play["ask"]))
    lines.append("Do not: " + play["avoid"])
    lines.append("Next step: book a specific callback or appointment; record the outcome in the app.")
    return "\n".join(lines)


def build_brief(lead, *, ai_summary: Optional[str] = None) -> str:
    key = _playbook_key(lead)
    play = PLAYBOOKS[key]
    address = _address(lead)
    county = f" | County: {lead.county}" if lead.county else ""
    facts = []
    if lead.score is not None:
        facts.append(f"score {round(float(lead.score), 1)}")
    if lead.heat:
        facts.append(f"heat {lead.heat}")
    if lead.equity_pct is not None:
        facts.append(f"equity {float(lead.equity_pct):g}%")
    flags = _flags(lead)
    if flags:
        facts.append("flags: " + ", ".join(flags))

    lines = [
        "[GreenSeed] Lead brief",
        f"Lead: {lead.full_name or 'Owner unknown'} | {lead.primary_phone or 'no phone'}",
        f"Property: {address}{county}",
        f"Type: {lead.lead_type or 'not recorded'} | Stage: {lead.source_status or lead.stage_code}",
    ]
    if facts:
        lines.append("Facts: " + " | ".join(facts))
    lines.append(f"Quick summary: {play['angle']}")
    if ai_summary:
        lines.append(f"AI summary (reviewed): {ai_summary.strip()[:400]}")
    lines.append("")
    lines.append("Ask the lead manager's five questions:")
    for index, question in enumerate(CORE_QUESTIONS, start=1):
        lines.append(f"{index}. {question}")
    lines.append("")
    lines.append(f"Playbook — {play['label']}:")
    lines.append("Opening: " + play["opening"].format(address=address))
    lines.append("Ask first: " + " ".join(play["ask"]))
    lines.append("Do not: " + play["avoid"])
    lines.append("Next step: book a specific callback or appointment; record the outcome in the app.")
    lines.append("Prepared locally by Green Seed. No message was sent to the seller.")

    text = "\n".join(lines)
    if len(text) > MAX_BRIEF:
        text = text[: MAX_BRIEF - 3].rstrip() + "..."
    return text


def playbook_for(lead):
    """The public playbook entry (label, opening, ask-first, avoid) for this lead type."""
    return PLAYBOOKS[_playbook_key(lead)]
