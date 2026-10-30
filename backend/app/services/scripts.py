"""Deterministic call scripts, generated only from the lead's recorded facts.

No model call and no invented ARV, repair or offer numbers. The script is stored as a
local activity only when the operator asks for it; it is never sent to a seller.
"""

from ..models import Activity, Lead


def _address(lead: Lead) -> str:
    prop = lead.properties[0] if lead.properties else None
    if prop is None:
        return "the property"
    parts = [prop.street_address, prop.city, prop.state]
    return ", ".join(part for part in parts if part) or "the property"


def build_script(lead: Lead) -> dict:
    name = lead.first_name or lead.full_name or "the owner"
    address = _address(lead)
    prop = lead.properties[0] if lead.properties else None
    price = getattr(prop, "asking_price", None) if prop else None
    price_line = (
        f"The recorded asking price is {price:,.0f} dollars."
        if price
        else "No asking price is recorded, so ask for their number before discussing ours."
    )
    return {
        "objective": f"Confirm motivation, condition and timeline for {address}, and book the next concrete step.",
        "steps": [
            {
                "step_number": 1,
                "title": "Opening",
                "content": (
                    f"Hi {name}, this is Jason with GreenSeedTX. I'm calling about {address}. "
                    "Is now still a good time for two minutes?"
                ),
                "tips": "If it is not a good time, ask for a specific callback window instead of pushing.",
            },
            {
                "step_number": 2,
                "title": "Confirm the situation",
                "content": (
                    "I buy houses as-is for cash. Before I ask anything else — is the property still "
                    "something you would consider selling this year?"
                ),
                "tips": "A clear no ends the call politely; a maybe is the real start of the conversation.",
            },
            {
                "step_number": 3,
                "title": "Discovery",
                "content": (
                    "What would need to happen for you to be open to selling? "
                    "How soon are you hoping to close? "
                    "What condition is the property in today? "
                    "Is there a mortgage or lien on it?"
                ),
                "tips": "Write the seller's own words down; do not translate them into a score yet.",
            },
            {
                "step_number": 4,
                "title": "Numbers",
                "content": (
                    f"{price_line} I will not throw out a number I cannot support — I would rather "
                    "look at the condition and recent sales and come back with a real range."
                ),
                "tips": "Never invent ARV or repair numbers on the call.",
            },
            {
                "step_number": 5,
                "title": "Close for the next step",
                "content": (
                    "Based on what you told me, the next step is for me to review the numbers and "
                    "come back to you. Would tomorrow afternoon or the morning after work better?"
                ),
                "tips": "A booked time is the win; a 'sounds good' is not.",
            },
        ],
        "key_objections": [
            {
                "objection": "I want full retail price.",
                "response": "I understand. A cash offer has to account for repairs and closing costs, so it will not match retail. If retail is the goal, an agent may serve you better and I will say so.",
            },
            {
                "objection": "I need to think about it.",
                "response": "Of course. What is the one thing you need to know before you can decide? I can get you that answer instead of calling you again with nothing new.",
            },
            {
                "objection": "I already have an agent.",
                "response": "That is fine. I am not asking you to break that relationship. If the listing expires or the timeline changes, you can keep my number.",
            },
            {
                "objection": "How did you get my information?",
                "response": "Your property came up in public records and marketing data. If you would rather I not call again, tell me now and I will record it.",
            },
        ],
        "next_step": "Record the outcome, then keep the follow-up the app suggests or replace it with the seller's chosen time.",
        "source": "local_rules",
    }


def script_text(script: dict) -> str:
    lines = [f"Objective: {script['objective']}", ""]
    for step in script["steps"]:
        lines.append(f"{step['step_number']}. {step['title']}")
        lines.append(step["content"])
        lines.append(f"Tip: {step['tips']}")
        lines.append("")
    lines.append("Likely objections:")
    for item in script["key_objections"]:
        lines.append(f"- {item['objection']} -> {item['response']}")
    lines.append("")
    lines.append(f"Next step: {script['next_step']}")
    return "\n".join(lines)


def save_as_note(db, lead: Lead, text: str) -> Activity:
    activity = Activity(
        lead_id=lead.id,
        activity_type="note",
        source="local",
        summary=text[:20000],
        source_metadata={"kind": "call_script", "generated_locally": True},
    )
    db.add(activity)
    db.commit()
    db.refresh(activity)
    return activity
